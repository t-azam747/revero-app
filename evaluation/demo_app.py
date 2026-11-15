"""Isolated offline demo app. Never run against the personal inbox."""
from datetime import datetime, timedelta
import os
from pathlib import Path

from .fixtures import FixtureProvider, FixtureAnswerer, FixtureMessenger, seed
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import DEFAULT_DB, create_app
from app.extraction import connect, run_one

raw = os.environ.get('REVERO_DEMO_DB')
if not raw:
    raise RuntimeError('Use the demo recorder, which supplies an isolated temporary database.')
path = Path(raw).resolve()
if path == DEFAULT_DB:
    raise RuntimeError('The offline demo must not use the personal inbox.')
provider, messenger = FixtureProvider(), FixtureMessenger()
with TestClient(create_app(path, answerer=FixtureAnswerer(), messenger=messenger)) as bootstrap:
    ids, provider = seed(bootstrap, path, provider=provider, retry=True)
    content = bootstrap.get(f"/api/reels/{ids['caption-only']}/content").json()['job']
    bootstrap.post('/api/actions', json={'job_id': content['id'], 'suggestion_index': 0}).raise_for_status()

app = create_app(path, answerer=FixtureAnswerer(), messenger=messenger)


@app.post('/demo/process/{reel_id}')
def process_fixture(reel_id: int):
    with connect(path) as db:
        row = db.execute('SELECT active_job FROM reels WHERE id=?', (reel_id,)).fetchone()
    if not row or not row['active_job']:
        raise HTTPException(404, 'Attach the authored demo caption first.')
    run_one(path, provider)
    return {'processed': True, 'provider': 'deterministic offline fixture'}


@app.get('/demo/deliveries')
def deliveries():
    return {'simulated_message_parts': len(messenger.sent), 'real_telegram_messages': 0}
