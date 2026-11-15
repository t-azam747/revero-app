"""Instagram pilot intake and outbox. No media downloads or model calls."""
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import time
import uuid

import httpx
from dotenv import dotenv_values
from fastapi import HTTPException

from .extraction import ROOT, connect, enqueue
from .main import canonicalize, initialize_database

log = logging.getLogger('uvicorn.error')
MAX_BODY = 1024 * 1024


@dataclass(frozen=True)
class Config:
    app_secret: str = ''
    verify_token: str = ''
    account_id: str = ''
    sender_id: str = ''
    access_token: str = ''
    api_version: str = ''
    replies_enabled: bool = False
    login_flow: str = 'instagram'

    @property
    def api_host(self):
        hosts = {'instagram': 'graph.instagram.com', 'unified': 'graph.facebook.com'}
        if self.login_flow not in hosts:
            raise ValueError('Unsupported Instagram login flow.')
        return hosts[self.login_flow]


def settings():
    values = {**dotenv_values(ROOT / '.env'), **os.environ}
    return Config(**{key: (values.get('INSTAGRAM_' + key.upper()) or '') for key in
                     ('app_secret', 'verify_token', 'account_id', 'sender_id', 'access_token', 'api_version')},
                  replies_enabled=values.get('INSTAGRAM_REPLIES_ENABLED') == 'true',
                  login_flow=values.get('INSTAGRAM_LOGIN_FLOW') or 'instagram')


def initialize(path):
    initialize_database(path)
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS instagram_senders (
            account_id TEXT NOT NULL, sender_id TEXT NOT NULL, first_seen REAL NOT NULL,
            PRIMARY KEY(account_id, sender_id));
        CREATE TABLE IF NOT EXISTS instagram_inbound (
            id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, mid TEXT NOT NULL,
            sender_id TEXT NOT NULL, event_at REAL NOT NULL, received_at REAL NOT NULL,
            kind TEXT NOT NULL, UNIQUE(account_id, mid));
        CREATE TABLE IF NOT EXISTS instagram_refs (
            account_id TEXT NOT NULL, identity TEXT NOT NULL, reel_id INTEGER NOT NULL REFERENCES reels(id),
            PRIMARY KEY(account_id, identity));
        CREATE TABLE IF NOT EXISTS instagram_shares (
            inbound_id INTEGER NOT NULL REFERENCES instagram_inbound(id), position INTEGER NOT NULL,
            reel_id INTEGER NOT NULL REFERENCES reels(id), attachment_type TEXT NOT NULL,
            provider_id TEXT, reference TEXT, title TEXT,
            access_class TEXT NOT NULL DEFAULT 'unmeasured',
            PRIMARY KEY(inbound_id, position));
        CREATE TABLE IF NOT EXISTS instagram_outbox (
            id INTEGER PRIMARY KEY, inbound_id INTEGER NOT NULL REFERENCES instagram_inbound(id),
            kind TEXT NOT NULL DEFAULT 'saved', text TEXT,
            state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL DEFAULT 0, lease_until REAL, attempt_id TEXT,
            provider_mid TEXT, error TEXT,
            UNIQUE(inbound_id, kind));
        ''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(instagram_outbox)')}
        if 'kind' not in columns:
            db.execute("ALTER TABLE instagram_outbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'saved'")
        if 'text' not in columns:
            db.execute("ALTER TABLE instagram_outbox ADD COLUMN text TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_instagram_outbox_inbound_kind ON instagram_outbox(inbound_id, kind)")


def obj(value):
    return value if isinstance(value, dict) else {}


def items(value):
    return value if isinstance(value, list) else []


def text(value, maximum=2000):
    return value if isinstance(value, str) and 0 < len(value) <= maximum else None


def permalink(value):
    try:
        return canonicalize(value) if isinstance(value, str) else None
    except HTTPException:
        return None


def save_share(db, config, provider_id, reference):
    canonical = permalink(reference)
    identity = 'id:' + provider_id if provider_id else 'url:' + canonical[1]
    existing = db.execute('SELECT reel_id FROM instagram_refs WHERE account_id=? AND identity=?',
                          (config.account_id, identity)).fetchone()
    if existing:
        # Enrich a reference-only save when its canonical permalink becomes available.
        row = db.execute('SELECT url FROM reels WHERE id=?', (existing['reel_id'],)).fetchone()
        if canonical and not row['url']:
            collision = db.execute('SELECT id FROM reels WHERE shortcode=?', (canonical[0],)).fetchone()
            if collision and collision['id'] != existing['reel_id']:
                # A manual permalink save can predate enrichment of this provider-only share.
                # Preserve jobs/actions and their IDs while collapsing the two inbox entries.
                source, target = existing['reel_id'], collision['id']
                source_row = db.execute('SELECT * FROM reels WHERE id=?', (source,)).fetchone()
                target_row = db.execute('SELECT * FROM reels WHERE id=?', (target,)).fetchone()
                # Retain identical historical revisions too, without violating the per-Reel key.
                for job in db.execute('SELECT id,revision FROM extraction_jobs WHERE reel_id=?', (source,)).fetchall():
                    if db.execute('SELECT 1 FROM extraction_jobs WHERE reel_id=? AND revision=?', (target, job['revision'])).fetchone():
                        db.execute('UPDATE extraction_jobs SET revision=? WHERE id=?',
                                   ('merged:' + str(job['id']) + ':' + job['revision'], job['id']))
                db.execute('UPDATE extraction_jobs SET reel_id=? WHERE reel_id=?', (target, source))
                db.execute('UPDATE actions SET reel_id=? WHERE reel_id=?', (target, source))
                db.execute('UPDATE instagram_refs SET reel_id=? WHERE reel_id=?', (target, source))
                db.execute('UPDATE instagram_shares SET reel_id=? WHERE reel_id=?', (target, source))
                if not target_row['active_job'] and source_row['active_job']:
                    db.execute('UPDATE reels SET active_job=?,status=? WHERE id=?',
                               (source_row['active_job'], source_row['status'], target))
                db.execute('DELETE FROM reels WHERE id=?', (source,))
                return target
            if not collision:
                db.execute('UPDATE reels SET shortcode=?,url=? WHERE id=?', (*canonical, existing['reel_id']))
        return existing['reel_id']
    if canonical:
        shortcode, url = canonical
    else:
        # Internal key cannot collide with a legal Instagram shortcode. Empty URL means unknown.
        shortcode = 'instagram:' + hashlib.sha256((config.account_id + ':' + identity).encode()).hexdigest()
        url = ''
    db.execute('INSERT INTO reels(shortcode,url) VALUES (?,?) ON CONFLICT(shortcode) DO NOTHING', (shortcode, url))
    reel_id = db.execute('SELECT id FROM reels WHERE shortcode=?', (shortcode,)).fetchone()['id']
    db.execute('INSERT INTO instagram_refs VALUES (?,?,?)', (config.account_id, identity, reel_id))
    return reel_id


def intake(path, payload, config, now=None):
    now = time.time() if now is None else now
    counts = dict(messages=0, shares=0, replays=0, ignored=0)
    if obj(payload).get('object') != 'instagram':
        return counts
    entries = items(payload.get('entry'))
    log.info('instagram envelope entries=%d messaging=%d changes=%d', len(entries),
             sum(len(items(obj(entry).get('messaging'))) for entry in entries),
             sum(len(items(obj(entry).get('changes'))) for entry in entries))
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        for entry in items(payload.get('entry')):
            entry = obj(entry)
            if entry.get('id') != config.account_id or not config.account_id:
                continue
            for event in items(entry.get('messaging')):
                event = obj(event)
                message = obj(event.get('message'))
                sender = text(obj(event.get('sender')).get('id'), 100)
                if (obj(event.get('recipient')).get('id') != config.account_id or not sender
                    or sender == config.account_id or message.get('is_echo') or message.get('is_deleted')
                    or message.get('is_unsupported') or not text(message.get('mid'), 1000)):
                    counts['ignored'] += 1
                    continue
                # Bootstrap records scoped IDs only, never message text, URLs, or a reply.
                db.execute('INSERT OR IGNORE INTO instagram_senders VALUES (?,?,?)', (config.account_id, sender, now))
                if sender != config.sender_id or not config.sender_id:
                    counts['ignored'] += 1
                    continue
                timestamp = event.get('timestamp')
                if isinstance(timestamp, bool) or not isinstance(timestamp, (float, int)) or not 0 < timestamp <= (now + 300) * 1000:
                    counts['ignored'] += 1
                    continue
                shares = []
                for attachment in items(message.get('attachments')):
                    attachment = obj(attachment)
                    if attachment.get('type') not in ('ig_reel', 'reel'):
                        continue
                    data = obj(attachment.get('payload'))
                    provider = data.get('reel_video_id')
                    if isinstance(provider, int) and not isinstance(provider, bool):
                        provider = str(provider)
                    provider = text(provider, 200)
                    reference = text(data.get('url'), 10000)
                    if provider or permalink(reference):
                        shares.append((attachment['type'], provider, reference, text(data.get('title'), 20000)))
                # Plain text DM links use the existing strict manual URL validation.
                if not shares and permalink(message.get('text')):
                    shares.append(('text_url', None, message['text'], None))
                if not shares and not text(message.get('text'), 20000):
                    counts['ignored'] += 1
                    continue
                cursor = db.execute('''INSERT INTO instagram_inbound(account_id,mid,sender_id,event_at,received_at,kind)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(account_id,mid) DO NOTHING''',
                    (config.account_id, message['mid'], sender, timestamp / 1000, now, 'reel' if shares else 'text'))
                if not cursor.rowcount:
                    counts['replays'] += 1
                    continue
                inbound_id = cursor.lastrowid
                counts['messages'] += 1
                for position, (kind, provider, reference, title) in enumerate(shares):
                    reel_id = save_share(db, config, provider, reference)
                    db.execute('''INSERT INTO instagram_shares(inbound_id,position,reel_id,attachment_type,provider_id,reference,title)
                        VALUES (?,?,?,?,?,?,?)''', (inbound_id, position, reel_id, kind, provider, reference, title))
                    # Queue the supplied share title as a caption-only job in the same transaction.
                    # Reused ready revisions are cached; manual content is never overwritten.
                    if title:
                        enqueue(db, reel_id, title, only_if_empty=True)
                    counts['shares'] += 1
                if shares:
                    db.execute('INSERT INTO instagram_outbox(inbound_id) VALUES (?)', (inbound_id,))
    log.info('instagram intake messages=%d shares=%d replays=%d ignored=%d', *counts.values())
    return counts


class SendFailure(Exception):
    def __init__(self, state, code, delay=0):
        self.state, self.code, self.delay = state, code, delay


class InstagramSender:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport

    def send(self, recipient, message_text='Saved'):
        cfg = self.config
        # Host is selected from a fixed allowlist; account and API version never become arbitrary URL paths.
        try:
            host = cfg.api_host
        except ValueError:
            raise SendFailure('failed', 'configuration') from None
        if not (re.fullmatch(r'\d+', cfg.account_id) and re.fullmatch(r'v\d+\.\d+', cfg.api_version) and cfg.access_token):
            raise SendFailure('failed', 'configuration')
        for name in ('httpx', 'httpcore'):
            logging.getLogger(name).setLevel(logging.WARNING)
        try:
            with httpx.Client(transport=self.transport, timeout=20, follow_redirects=False) as client:
                response = client.post(f'https://{host}/{cfg.api_version}/{cfg.account_id}/messages',
                    headers={'Authorization': f'Bearer {cfg.access_token}'},
                    json={'recipient': {'id': recipient}, 'message': {'text': message_text}})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise SendFailure('queued', 'connection', 60) from None
        except httpx.HTTPError:
            raise SendFailure('uncertain', 'transport') from None
        if response.status_code == 429:
            raise SendFailure('queued', 'rate_limited', 300)
        if response.status_code >= 500:
            raise SendFailure('uncertain', 'server')
        if not 200 <= response.status_code < 300:
            raise SendFailure('failed', 'rejected')
        try:
            mid = text(response.json().get('message_id'), 1000)
        except (ValueError, AttributeError):
            mid = None
        if not mid:
            raise SendFailure('uncertain', 'invalid_response')
        return mid


def format_summary_message(takeaway, reel_url, caption_only=True):
    """Format a concise delivery message: summary, top 2 takeaways/suggestions, source link, and medium label."""
    lines = [f"Takeaway ({'text-based' if caption_only else 'video analysis'}):"]
    lines.append(takeaway.get('summary', '')[:500])
    suggestions = takeaway.get('suggestions', [])
    if suggestions:
        lines.append("\nKey suggestions:")
        for s in suggestions[:2]:
            lines.append(f"• {s['text'][:200]}")
    if reel_url:
        lines.append(f"\n{reel_url}")
    return "\n".join(lines)[:1000]


def queue_summary_replies(db):
    """Queue concise summary deliveries for shares that reached ready state within the reply window."""
    rows = db.execute('''
        SELECT s.inbound_id, s.reel_id, r.url, j.result, j.mime, i.event_at
        FROM instagram_shares s
        JOIN instagram_inbound i ON i.id = s.inbound_id
        JOIN reels r ON r.id = s.reel_id
        JOIN extraction_jobs j ON j.id = r.active_job
        WHERE r.status = 'ready' AND j.state = 'ready' AND j.result IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM instagram_outbox o WHERE o.inbound_id = s.inbound_id AND o.kind = 'summary')
    ''').fetchall()
    for row in rows:
        takeaway = json.loads(row['result'])
        msg = format_summary_message(takeaway, row['url'], caption_only=row['mime'] is None)
        db.execute('''INSERT INTO instagram_outbox(inbound_id, kind, text)
                      VALUES (?, 'summary', ?)
                      ON CONFLICT(inbound_id, kind) DO NOTHING''', (row['inbound_id'], msg))


def run_one(path, config, sender=None, now=None):
    now = time.time() if now is None else now
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE instagram_outbox SET state='uncertain', error='interrupted' WHERE state='sending' AND lease_until<=?", (now,))
        if not config.replies_enabled or not config.account_id or not config.sender_id:
            return False
        # Queue any completed takeaways for summary delivery
        queue_summary_replies(db)
        row = db.execute('''SELECT o.*,i.sender_id,i.event_at FROM instagram_outbox o JOIN instagram_inbound i ON i.id=o.inbound_id
            WHERE o.state='queued' AND o.available_at<=? AND i.account_id=? AND i.sender_id=? ORDER BY o.id LIMIT 1''',
                         (now, config.account_id, config.sender_id)).fetchone()
        if not row:
            return False
        if now >= row['event_at'] + 86400:
            db.execute("UPDATE instagram_outbox SET state='expired',error='reply_window' WHERE id=?", (row['id'],))
            return True
        if row['attempts'] >= 4:
            db.execute("UPDATE instagram_outbox SET state='failed',error='attempt_limit' WHERE id=?", (row['id'],))
            return True
        attempt = uuid.uuid4().hex
        db.execute("UPDATE instagram_outbox SET state='sending',attempts=attempts+1,attempt_id=?,lease_until=? WHERE id=?", (attempt, now+120, row['id']))
    try:
        msg_text = row['text'] or 'Saved'
        # Support senders accepting (recipient) or (recipient, text)
        send_fn = (sender or InstagramSender(config)).send
        import inspect
        sig = inspect.signature(send_fn)
        if len(sig.parameters) >= 2 or any(p.kind == p.VAR_POSITIONAL for p in sig.parameters.values()):
            provider_mid = send_fn(row['sender_id'], msg_text)
        else:
            provider_mid = send_fn(row['sender_id'])
        state, error, delay = 'sent', None, 0
    except SendFailure as exc:
        state, error, delay, provider_mid = exc.state, exc.code, exc.delay, None
    except Exception:
        state, error, delay, provider_mid = 'uncertain', 'unexpected', 0, None
    with connect(path) as db:
        db.execute('''UPDATE instagram_outbox SET state=?,error=?,available_at=?,provider_mid=?
            WHERE id=? AND state='sending' AND attempt_id=?''', (state, error, now+delay, provider_mid, row['id'], attempt))
    log.info('instagram reply outcome=%s', state)
    return True
