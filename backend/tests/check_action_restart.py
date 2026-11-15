"""Optional real-process check: run from backend with .venv/bin/python tests/check_action_restart.py."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.extraction import run_one
from app.digest import run_digest


class FixtureMessenger:
    def __init__(self): self.sent = []
    def send(self, text):
        self.sent.append(text)
        return len(self.sent)


class FixtureProvider:
    def extract(self, caption, *args):
        return {'summary': 'Practice joins.', 'topics': ['SQLite'],
                'suggestions': [{'text': 'Practice joins', 'source_index': 0}],
                'date_candidates': [{'original_text': 'tomorrow', 'source_index': 0}],
                'sources': [{'excerpt': caption, 'origin': 'caption', 'timestamp_seconds': None}]}


def main():
    with tempfile.TemporaryDirectory(prefix='revero-actions-restart-') as directory:
        database = Path(directory) / 'revero.sqlite3'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'REVERO_DB_PATH': str(database)}
        action_id = None
        messenger = FixtureMessenger()
        for phase in range(3):
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--app-dir', str(ROOT),
                                       '--host', '127.0.0.1', '--port', str(port)],
                                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for attempt in range(100):
                    if server.poll() is not None:
                        raise RuntimeError('Test server exited before startup.')
                    try:
                        if httpx.get(base + '/api/reels', timeout=0.2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError('Test server startup timed out.')
                if phase == 0:
                    reel = httpx.post(base + '/api/reels', json={'url': 'https://www.instagram.com/reel/Restart/'}).json()
                    job = httpx.post(base + f"/api/reels/{reel['id']}/content", data={'caption': 'Practice joins tomorrow.'}).json()
                    assert run_one(database, FixtureProvider())
                    action = httpx.post(base + '/api/actions', json={'job_id': job['id'], 'suggestion_index': 0}).json()
                    action_id = action['id']
                    assert httpx.patch(base + f'/api/actions/{action_id}', json={'due_date': '2027-02-01'}).status_code == 200
                    assert httpx.put(base + '/api/digest/preferences', json={'interests': ['SQLite'], 'enabled': False, 'delivery_time': '20:45'}).status_code == 200
                    assert run_digest(database, messenger)['state'] == 'sent'
                elif phase == 1:
                    assert httpx.get(base + '/api/search?q=joins').json()['sources']
                    assert httpx.get(base + '/api/digest').json()['preferences']['interests'] == ['sqlite']
                    assert httpx.get(base + '/api/digest').json()['preferences']['delivery_time'] == '20:45'
                    assert run_digest(database, messenger)['state'] == 'sent'
                    assert len(messenger.sent) == 1
                    action = httpx.get(base + '/api/actions').json()[0]
                    assert action['id'] == action_id and action['due_date'] == '2027-02-01'
                    assert action['date_mentions'] == ['tomorrow']
                    assert httpx.patch(base + f'/api/actions/{action_id}', json={'status': 'done'}).status_code == 200
                else:
                    assert httpx.get(base + '/api/actions').json() == []
                    assert httpx.get(base + '/api/actions?status=done').json()[0]['id'] == action_id
            finally:
                server.terminate()
                server.wait(timeout=10)
        print('Verified across two API process restarts: actions/dates/completion, search index, digest preferences, and sent-run deduplication persist. No real provider calls.')


if __name__ == '__main__':
    main()
