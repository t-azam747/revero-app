"""Deterministic digests and conservative, durable Telegram delivery."""
from datetime import datetime, timedelta, timezone, date
import json
import logging
import os
import re
import time
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .extraction import ROOT, connect

# Telegram credentials are part of its URL; do not allow HTTP request tracing to log them.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
IST = ZoneInfo('Asia/Kolkata')


def configuration():
    from dotenv import dotenv_values
    values = {**dotenv_values(ROOT / '.env'), **os.environ}
    return {name: values.get(name, '') for name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')}


def telegram_configured():
    values = configuration()
    return bool(re.fullmatch(r'\d+:[A-Za-z0-9_-]+', values['TELEGRAM_BOT_TOKEN']) and re.fullmatch(r'\d+', values['TELEGRAM_CHAT_ID']))



def preferences(path):
    with connect(path) as db:
        row = db.execute('SELECT * FROM digest_preferences WHERE id=1').fetchone()
    return {'interests': json.loads(row['interests']), 'enabled': bool(row['enabled']), 'telegram_configured': telegram_configured(),
            'delivery_time': row['delivery_time'], 'timezone': 'Asia/Kolkata',
            'schedule': row['delivery_time'] + ' Asia/Kolkata'}


def build(path, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(IST)
    today = local.date()
    prefs = preferences(path)
    with connect(path) as db:
        rows = db.execute('''SELECT r.*, j.result FROM reels r JOIN extraction_jobs j ON j.id=r.active_job
                             WHERE r.status='ready' AND j.state='ready' AND j.result IS NOT NULL''').fetchall()
        deadlines = [dict(row) for row in db.execute('''SELECT a.id, a.text, a.due_date, r.url FROM actions a
            JOIN reels r ON r.id=a.reel_id WHERE a.status='open' AND a.due_date IS NOT NULL AND a.due_date<=?
            ORDER BY a.due_date, a.id''', ((today+timedelta(days=7)).isoformat(),))]
        unreadable = db.execute("SELECT count(*) FROM reels WHERE status IN ('needs_content','failed')").fetchone()[0]
        pending = db.execute("SELECT count(*) FROM reels WHERE status!='ready'").fetchone()[0]
    # Include readable saves from this India-local day.
    start = datetime.combine(today, datetime.min.time(), tzinfo=IST).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    rows = [row for row in rows if start <= datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')) < end]
    ranked = rank_reels(rows, prefs['interests'])
    return {'local_date': today.isoformat(), 'picks': ranked[:3], 'deadlines': deadlines,
            'pending_count': pending, 'unreadable_count': unreadable, 'processing_count': pending-unreadable, 'readable_count': len(ranked), 'interests': prefs['interests'],
            'readable_reels': ranked}


def rank_reels(rows, interests):
    """Return the complete deterministic ranking for a shared evaluation candidate pool."""
    ranked = []
    for row in rows:
        takeaway = json.loads(row['result'])
        corpus = ' '.join([takeaway['summary'], *takeaway['topics'], *(item['text'] for item in takeaway['suggestions'])]).lower()
        hits = [interest for interest in interests if re.search(r'(?<!\w)' + re.escape(interest.lower()) + r'(?!\w)', corpus)]
        concrete = min(len(takeaway['suggestions']), 3)
        evidence = min(len(takeaway['sources']), 3)
        score = len(hits)*100 + concrete*10 + evidence
        ranked.append({'id': row['id'], 'url': row['url'], 'shortcode': row['shortcode'],
                       'summary': takeaway['summary'], 'score': score, 'created_at': row['created_at'],
                       'reasons': {'interest_matches': hits, 'actionable_suggestions': concrete, 'source_count': evidence}})
    ranked.sort(key=lambda reel: (reel['score'], reel['created_at'], reel['id']), reverse=True)
    return ranked

def utf16_size(text):
    return len(text.encode('utf-16-le'))//2


def messages(payload):
    # Plain text avoids model/user-controlled Markdown and preserves original links.
    blocks = [f"Revero | {payload['local_date']}\nToday’s most useful takeaways"]
    for index, reel in enumerate(payload['picks'], 1):
        blocks.append(f"{index}. {reel['summary'][:500]}\n{reel['url']}")
    other = [reel for reel in payload.get('readable_reels', []) if reel['id'] not in {pick['id'] for pick in payload['picks']}]
    if other:
        blocks.append('More readable Reels saved today')
        for reel in other:
            blocks.append(f"{reel['summary'][:500]}\n{reel['url']}")
    if not payload['picks']:
        blocks.append('No ready Reels yet.')
    blocks.append('Upcoming and overdue actions (next 7 days)')
    for action in payload['deadlines']:
        blocks.append(f"{action['due_date']}: {action['text'][:1000]}\n{action['url']}")
    if not payload['deadlines']:
        blocks.append('No confirmed deadlines.')
    blocks.append(f"{payload['pending_count']} saved link(s) still need content or processing.")
    if 'unreadable_count' in payload:
        blocks.append(f"{payload['unreadable_count']} need readable content or have failed processing; {payload['processing_count']} queued or processing.")
    chunks, current = [], ''
    for block in blocks:
        if utf16_size(current + '\n\n' + block) > 3800:
            chunks.append(current)
            current = block
        else:
            current += ('\n\n' if current else '') + block
    if current:
        chunks.append(current)
    return chunks


class DeliveryError(Exception):
    def __init__(self, message, uncertain=False, retry_after=3600):
        super().__init__(message)
        self.uncertain, self.retry_after = uncertain, retry_after


class TelegramMessenger:
    def send(self, text):
        values = configuration()
        try:
            response = httpx.post(f"https://api.telegram.org/bot{values['TELEGRAM_BOT_TOKEN']}/sendMessage",
                                  json={'chat_id': values['TELEGRAM_CHAT_ID'], 'text': text,
                                        'link_preview_options': {'is_disabled': True}}, timeout=20)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise DeliveryError('Could not connect to Telegram. Retry in one minute.', retry_after=60)
        except httpx.HTTPError:
            raise DeliveryError('Telegram delivery is uncertain. Check the chat before choosing how to resolve it.', uncertain=True)
        try:
            data = response.json()
        except ValueError:
            raise DeliveryError('Telegram returned an unreadable response. Check the chat before retrying.', uncertain=True)
        if response.status_code >= 500:
            raise DeliveryError('Telegram returned a server error; delivery is uncertain. Check the chat.', uncertain=True)
        if response.status_code == 429 or data.get('error_code') == 429:
            delay = data.get('parameters', {}).get('retry_after', 60)
            delay = max(30, min(int(delay), 86400)) if isinstance(delay, (int, float)) else 60
            raise DeliveryError('Telegram rate limit reached. Delivery is deferred.', retry_after=delay)
        if not response.is_success or not data.get('ok'):
            raise DeliveryError('Telegram rejected delivery. Check the bot token and private chat ID before retrying.')
        identifier = data.get('result', {}).get('message_id')
        if not isinstance(identifier, int):
            raise DeliveryError('Telegram did not confirm a message ID. Check the chat.', uncertain=True)
        return identifier


def recover_uncertain(path, epoch=None, manual=False):
    runs = "digest_manual_runs" if manual else "digest_runs"
    parts = "digest_manual_messages" if manual else "digest_messages"
    epoch = time.time() if epoch is None else epoch
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        stale = [row['local_date'] for row in db.execute(f"SELECT local_date FROM {runs} WHERE state='sending' AND started_at < ?", (epoch-120,))]
        for day in stale:
            db.execute(f"UPDATE {runs} SET state='uncertain', attempt=NULL, error='Worker stopped during delivery. Review Telegram before retrying.' WHERE local_date=?", (day,))
            db.execute(f"UPDATE {parts} SET state='uncertain' WHERE local_date=? AND state='sending'", (day,))


def run_digest(path, messenger=None, now=None, *, manual_key=None):
    runs = "digest_manual_runs" if manual_key else "digest_runs"
    parts = "digest_manual_messages" if manual_key else "digest_messages"
    from .operations import paused
    if paused(path, 'delivery'): raise HTTPException(409, 'Delivery is paused for recovery review.')
    clock = time.time if now is None else lambda: now.timestamp()
    now = now or datetime.now(timezone.utc)
    epoch = now.timestamp()
    day = manual_key or now.astimezone(IST).date().isoformat()
    if messenger is None and not telegram_configured():
        raise HTTPException(503, 'Configure TELEGRAM_BOT_TOKEN and a numeric private TELEGRAM_CHAT_ID in the ignored .env first.')
    recover_uncertain(path, epoch, manual=bool(manual_key))
    payload = build(path, now)
    attempt_id = uuid.uuid4().hex
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute(f"INSERT OR IGNORE INTO {runs}(local_date, state, payload) VALUES (?, 'pending', ?)", (day, json.dumps(payload)))
        row = db.execute(f'SELECT * FROM {runs} WHERE local_date=?', (day,)).fetchone()
        if row['state'] == 'sending':
            if row['started_at'] < epoch - 120:
                db.execute(f"UPDATE {runs} SET state='uncertain', attempt=NULL, error='Worker stopped during delivery. Review the chat before retrying.' WHERE local_date=?", (day,))
                db.execute(f"UPDATE {parts} SET state='uncertain' WHERE local_date=? AND state='sending'", (day,))
                return {'local_date': day, 'state': 'uncertain'}
            return {'local_date': day, 'state': 'sending'}
        if row['state'] in {'sent', 'uncertain'} or row['next_attempt_at'] > epoch:
            return {'local_date': day, 'state': row['state']}
        existing = db.execute(f'SELECT count(*) FROM {parts} WHERE local_date=?', (day,)).fetchone()[0]
        if not existing:
            for position, text in enumerate(messages(json.loads(row['payload']))):
                db.execute(f'INSERT INTO {parts}(local_date, position, text) VALUES (?, ?, ?)', (day, position, text))
        db.execute(f"UPDATE {runs} SET state='sending', started_at=?, error=NULL, attempt=? WHERE local_date=?", (epoch, attempt_id, day))
    sender = messenger or TelegramMessenger()
    while True:
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute(f'SELECT state, attempt FROM {runs} WHERE local_date=?', (day,)).fetchone()
            if owner['attempt'] != attempt_id or owner['state'] != 'sending':
                return {'local_date': day, 'state': owner['state']}
            part = db.execute(f"SELECT * FROM {parts} WHERE local_date=? AND state!='sent' ORDER BY position LIMIT 1", (day,)).fetchone()
            if part is None:
                db.execute(f"UPDATE {runs} SET state='sent', sent_at=?, error=NULL WHERE local_date=?", (clock(), day))
                return {'local_date': day, 'state': 'sent'}
            db.execute(f"UPDATE {parts} SET state='sending' WHERE local_date=? AND position=?", (day, part['position']))
            db.execute(f'UPDATE {runs} SET started_at=? WHERE local_date=?', (clock(), day))
        try:
            message_id = sender.send(part['text'])
        except Exception as exc:
            known = isinstance(exc, DeliveryError)
            state = 'uncertain' if not known or exc.uncertain else 'failed'
            error = str(exc) if known else 'Delivery stopped unexpectedly. Check Telegram before retrying.'
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                owner = db.execute(f'SELECT state, attempt FROM {runs} WHERE local_date=?', (day,)).fetchone()
                if owner['attempt'] != attempt_id or owner['state'] != 'sending':
                    return {'local_date': day, 'state': owner['state']}
                db.execute(f'UPDATE {parts} SET state=? WHERE local_date=? AND position=?', (state, day, part['position']))
                db.execute(f'UPDATE {runs} SET state=?, error=?, next_attempt_at=? WHERE local_date=?',
                           (state, error, clock() + (exc.retry_after if known else 3600), day))
            return {'local_date': day, 'state': state}
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            owner = db.execute(f'SELECT state, attempt FROM {runs} WHERE local_date=?', (day,)).fetchone()
            if owner['attempt'] != attempt_id or owner['state'] != 'sending':
                return {'local_date': day, 'state': owner['state']}
            db.execute(f"UPDATE {parts} SET state='sent', message_id=? WHERE local_date=? AND position=?", (message_id, day, part['position']))


def tick(path, messenger=None, now=None):
    now = now or datetime.now(timezone.utc)
    from .operations import paused
    if paused(path, 'delivery'): return None
    recover_uncertain(path, now.timestamp())
    prefs = preferences(path)
    if not prefs['enabled'] or now.astimezone(IST).strftime('%H:%M') < prefs['delivery_time']:
        return None
    if messenger is None and not telegram_configured():
        return None
    return run_digest(path, messenger, now)


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interests: list[str] = Field(max_length=20)
    enabled: bool = Field(strict=True)
    delivery_time: str = Field(default='23:00', pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')

    @field_validator('interests')
    @classmethod
    def valid_interests(cls, values):
        if any(not value.strip() or len(value) > 80 for value in values):
            raise ValueError('Use up to 20 interests, each between 1 and 80 characters.')
        return list(dict.fromkeys(value.strip().lower() for value in values))


class ManualRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


def run_manual(path, request_id, messenger=None, now=None):
    now = now or datetime.now(timezone.utc)
    if messenger is None and not telegram_configured():
        raise HTTPException(503, 'Configure Telegram before sending.')
    recover_uncertain(path, now.timestamp(), manual=True)
    payload = build(path, now)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT run_key FROM digest_manual_requests WHERE request_id=?', (request_id,)).fetchone()
        if existing:
            key = existing['run_key']
        else:
            active = db.execute("SELECT local_date FROM digest_manual_runs WHERE state IN ('pending','sending','uncertain') ORDER BY rowid DESC LIMIT 1").fetchone()
            key = active['local_date'] if active else uuid.uuid4().hex
            if not active:
                db.execute("INSERT INTO digest_manual_runs(local_date,state,payload) VALUES (?,'pending',?)", (key,json.dumps(payload)))
            db.execute('INSERT OR IGNORE INTO digest_manual_requests VALUES (?,?)', (key,key))
            db.execute('INSERT OR IGNORE INTO digest_manual_requests VALUES (?,?)', (request_id,key))
    result = run_digest(path, messenger, now, manual_key=key)
    return {'request_id':request_id, 'run_id':key, 'state':result['state']}


class Resolution(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['delivered', 'not_delivered']


def router(path, messenger=None):
    routes = APIRouter()

    @routes.get('/api/digest')
    def preview():
        recover_uncertain(path)
        recover_uncertain(path, manual=True)
        with connect(path) as db:
            rows = db.execute('SELECT * FROM digest_runs ORDER BY local_date DESC LIMIT 14').fetchall()
            manual = db.execute('SELECT * FROM digest_manual_runs ORDER BY rowid DESC LIMIT 14').fetchall()
        prefs = preferences(path)
        if messenger is not None:
            prefs['telegram_configured'] = True
        return {'preview': build(path), 'preferences': prefs,
                'manual_runs': [{'run_id': row['local_date'], 'local_date': json.loads(row['payload'])['local_date'], **{key:row[key] for key in ('state','error','sent_at')}} for row in manual],
                'runs': [{key: row[key] for key in ('local_date', 'state', 'error', 'next_attempt_at', 'sent_at')} for row in rows]}

    @routes.put('/api/digest/preferences')
    def save_preferences(payload: Preferences):
        if payload.enabled and messenger is None and not telegram_configured():
            raise HTTPException(400, 'Configure Telegram before enabling scheduled delivery. Preview is available without credentials.')
        with connect(path) as db:
            db.execute('UPDATE digest_preferences SET interests=?, enabled=?, delivery_time=? WHERE id=1', (json.dumps(payload.interests), payload.enabled, payload.delivery_time))
        return preferences(path)

    @routes.post('/api/digest/send')
    def send(payload: ManualRequest):
        return run_manual(path, payload.request_id, messenger)

    def resolve_run(day, payload, manual=False):
        runs = 'digest_manual_runs' if manual else 'digest_runs'
        parts = 'digest_manual_messages' if manual else 'digest_messages'
        if not manual and payload.decision == 'not_delivered' and day != datetime.now(IST).date().isoformat():
            raise HTTPException(409, 'Only the current local date can be retried.')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            run = db.execute(f'SELECT * FROM {runs} WHERE local_date=?', (day,)).fetchone()
            if not run or run['state'] != 'uncertain':
                raise HTTPException(409, 'This run does not need uncertainty review.')
            state = 'sent' if payload.decision == 'delivered' else 'pending'
            db.execute(f"UPDATE {parts} SET state=? WHERE local_date=? AND state IN ('sending', 'uncertain')", (state, day))
            remaining = db.execute(f"SELECT count(*) FROM {parts} WHERE local_date=? AND state!='sent'", (day,)).fetchone()[0]
            state = 'failed' if remaining else 'sent'
            db.execute(f'UPDATE {runs} SET state=?, error=NULL, next_attempt_at=0, attempt=NULL, sent_at=? WHERE local_date=?',
                       (state, time.time() if state == 'sent' else None, day))
        return {'local_date': day, 'state': state}

    @routes.post('/api/digest/manual/{run_id}/resolve')
    def resolve_manual(run_id: str, payload: Resolution):
        return resolve_run(run_id, payload, True)

    @routes.post('/api/digest/{local_date}/resolve')
    def resolve(local_date: date, payload: Resolution):
        return resolve_run(local_date.isoformat(), payload)

    return routes
