"""Track persisted suggestions using server-side evidence snapshots."""
from datetime import date
import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .extraction import connect


class TrackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: int = Field(gt=0, strict=True)
    suggestion_index: int = Field(ge=0, strict=True)


class ActionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    due_date: str | None = None
    status: Literal['open', 'done', 'dismissed'] | None = None

    @field_validator('due_date')
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('Use a calendar date in YYYY-MM-DD format.')
            date.fromisoformat(value)
        return value

    @field_validator('status')
    @classmethod
    def valid_status(cls, value):
        if value is None:
            raise ValueError('Status cannot be null.')
        return value


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY,
        reel_id INTEGER NOT NULL REFERENCES reels(id),
        job_id INTEGER NOT NULL REFERENCES extraction_jobs(id),
        suggestion_index INTEGER NOT NULL,
        text TEXT NOT NULL, source_excerpt TEXT NOT NULL,
        source_origin TEXT NOT NULL, timestamp_seconds REAL,
        date_mentions TEXT NOT NULL,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'done', 'dismissed')),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE(job_id, suggestion_index))''')


def serialize(row):
    result = dict(row)
    result['date_mentions'] = json.loads(result['date_mentions'])
    result['due_date_confirmed'] = result['due_date'] is not None
    return result


SELECT = '''SELECT a.*, r.url, r.shortcode FROM actions a JOIN reels r ON r.id=a.reel_id'''


def router(path):
    routes = APIRouter()

    @routes.post('/api/actions')
    def track(payload: TrackInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute(SELECT + ' WHERE a.job_id=? AND a.suggestion_index=?',
                                  (payload.job_id, payload.suggestion_index)).fetchone()
            if existing:
                return {**serialize(existing), 'created': False}
            job = db.execute('''SELECT j.*, r.active_job FROM extraction_jobs j
                                JOIN reels r ON r.id=j.reel_id WHERE j.id=?''', (payload.job_id,)).fetchone()
            if not job:
                raise HTTPException(404, 'Takeaway not found.')
            if job['state'] != 'ready' or not job['result'] or job['active_job'] != job['id']:
                raise HTTPException(409, 'This takeaway has changed or is not ready. Reopen the Reel before tracking.')
            result = json.loads(job['result'])
            if payload.suggestion_index >= len(result['suggestions']):
                raise HTTPException(404, 'Suggestion not found.')
            item = result['suggestions'][payload.suggestion_index]
            source = result['sources'][item['source_index']]
            mentions = [candidate['original_text'] for candidate in result['date_candidates']
                        if candidate['source_index'] == item['source_index']]
            cursor = db.execute('''INSERT INTO actions
                (reel_id, job_id, suggestion_index, text, source_excerpt, source_origin, timestamp_seconds, date_mentions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (job['reel_id'], job['id'], payload.suggestion_index, item['text'], source['excerpt'],
                 source['origin'], source['timestamp_seconds'], json.dumps(mentions)))
            row = db.execute(SELECT + ' WHERE a.id=?', (cursor.lastrowid,)).fetchone()
        return {**serialize(row), 'created': True}

    @routes.get('/api/actions')
    def list_actions(status: Literal['open', 'done', 'dismissed', 'all'] = 'open', reel_id: int | None = None):
        clauses, parameters = [], []
        if status != 'all':
            clauses.append('a.status=?')
            parameters.append(status)
        if reel_id is not None:
            clauses.append('a.reel_id=?')
            parameters.append(reel_id)
        query = SELECT + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY a.id'
        with connect(path) as db:
            return [serialize(row) for row in db.execute(query, parameters)]

    @routes.patch('/api/actions/{action_id}')
    def update_action(action_id: int, payload: ActionUpdate):
        fields = payload.model_dump(exclude_unset=True)
        if not fields:
            raise HTTPException(400, 'Provide a due date or status to update.')
        # Column names come exclusively from the validated, extra-forbidden model.
        assignments = ', '.join(f'{name}=?' for name in fields)
        with connect(path) as db:
            cursor = db.execute(f"UPDATE actions SET {assignments}, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?",
                                (*fields.values(), action_id))
            if not cursor.rowcount:
                raise HTTPException(404, 'Action not found.')
            row = db.execute(SELECT + ' WHERE a.id=?', (action_id,)).fetchone()
        return serialize(row)

    return routes
