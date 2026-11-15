from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.extraction import connect, run_one

CAPTION = 'Practice joins tomorrow. Review indexes next week.'
RESULT = {'summary': 'Prepare for database interviews.', 'topics': ['SQLite'],
          'suggestions': [{'text': 'Practice joins', 'source_index': 0}, {'text': 'Review indexes', 'source_index': 1}],
          'date_candidates': [{'original_text': 'tomorrow', 'source_index': 0}, {'original_text': 'next week', 'source_index': 1}],
          'sources': [{'excerpt': 'Practice joins tomorrow.', 'origin': 'caption', 'timestamp_seconds': None},
                      {'excerpt': 'Review indexes next week.', 'origin': 'caption', 'timestamp_seconds': None}]}

class Provider:
    def extract(self, *args):
        return deepcopy(RESULT)

@pytest.fixture
def ready(tmp_path):
    path = tmp_path / 'actions.db'
    with TestClient(create_app(path)) as client:
        reel = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/Actions/'}).json()
        job = client.post(f"/api/reels/{reel['id']}/content", data={'caption': CAPTION}).json()
        assert run_one(path, Provider())
        yield client, path, reel['id'], job['id']

def track(client, job, index=0):
    response = client.post('/api/actions', json={'job_id': job, 'suggestion_index': index})
    assert response.status_code == 200, response.text
    return response.json()

def test_track_duplicate_and_concurrent_requests(ready):
    client, _, reel, job = ready
    first = track(client, job)
    assert first['created'] and first['status'] == 'open'
    assert first['text'] == 'Practice joins' and first['source_excerpt'] == 'Practice joins tomorrow.'
    assert first['date_mentions'] == ['tomorrow']
    assert first['due_date'] is None and not first['due_date_confirmed']
    assert first['source_origin'] == 'caption' and first['timestamp_seconds'] is None
    assert track(client, job) == {**first, 'created': False}
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(lambda _: track(client, job, 1), range(10)))
    assert len({row['id'] for row in rows}) == 1
    assert sum(row['created'] for row in rows) == 1
    assert len(client.get('/api/actions').json()) == 2

def test_confirm_correct_clear_date_and_restart(ready):
    client, path, reel, job = ready
    action = track(client, job)
    endpoint = f"/api/actions/{action['id']}"
    for due in ['2027-01-15', '2027-02-20', None]:
        response = client.patch(endpoint, json={'due_date': due})
        assert response.status_code == 200
        saved = response.json()
        assert saved['due_date'] == due and saved['due_date_confirmed'] == (due is not None)
        assert saved['date_mentions'] == ['tomorrow']
    client.patch(endpoint, json={'due_date': '2027-03-01'})
    with TestClient(create_app(path)) as restarted:
        saved = restarted.get('/api/actions').json()[0]
        assert saved['id'] == action['id'] and saved['due_date'] == '2027-03-01'
        assert track(restarted, job)['id'] == action['id']

def test_done_and_dismissed_leave_open_list(ready):
    client, path, _, job = ready
    done, dismissed = track(client, job), track(client, job, 1)
    assert client.patch(f"/api/actions/{done['id']}", json={'status': 'done'}).status_code == 200
    assert client.patch(f"/api/actions/{dismissed['id']}", json={'status': 'dismissed'}).status_code == 200
    assert client.get('/api/actions').json() == []
    assert client.get('/api/actions?status=done').json()[0]['id'] == done['id']
    assert client.get('/api/actions?status=dismissed').json()[0]['id'] == dismissed['id']
    assert track(client, job)['status'] == 'done'  # Repeated tracking does not reopen completed work.
    with TestClient(create_app(path)) as restarted:
        assert restarted.get('/api/actions').json() == []
        assert len(restarted.get('/api/actions?status=all').json()) == 2

def test_revision_change_preserves_evidence_and_rejects_stale_new_tracks(ready):
    client, _, reel, job = ready
    old = track(client, job)
    client.post(f'/api/reels/{reel}/content', data={'caption': 'Different text.'})
    assert track(client, job)['id'] == old['id']
    response = client.post('/api/actions', json={'job_id': job, 'suggestion_index': 1})
    assert response.status_code == 409
    assert client.get('/api/actions').json()[0]['source_excerpt'] == old['source_excerpt']

@pytest.mark.parametrize('payload', [
    {'due_date': 'tomorrow'}, {'due_date': '2027-02-30'}, {'due_date': '2027-2-3'},
    {'due_date': '2027-01-01T00:00:00Z'}, {'due_date': 12345}, {'status': 'unknown'},
    {'status': None}, {'text': 'Replace the evidence'}, {'due_date_confirmed': True},
])
def test_invalid_updates_preserve_action(ready, payload):
    client, _, _, job = ready
    action = track(client, job)
    assert client.patch(f"/api/actions/{action['id']}", json=payload).status_code == 422
    saved = client.get('/api/actions').json()[0]
    assert saved['due_date'] is None and saved['status'] == 'open'

def test_missing_and_unready_suggestions(ready):
    client, path, reel, job = ready
    assert client.post('/api/actions', json={'job_id': job, 'suggestion_index': 100}).status_code == 404
    assert client.post('/api/actions', json={'job_id': 99999, 'suggestion_index': 0}).status_code == 404
    assert client.post('/api/actions', json={'job_id': job, 'suggestion_index': -1}).status_code == 422
    assert client.post('/api/actions', json={'job_id': job, 'suggestion_index': 0, 'text': 'Forged text'}).status_code == 422
    assert client.patch('/api/actions/99999', json={'due_date': None}).status_code == 404
    assert client.patch('/api/actions/99999', json={}).status_code == 400
    assert client.get('/api/actions?status=bogus').status_code == 422
    with connect(path) as db:
        db.execute("UPDATE extraction_jobs SET state='failed' WHERE id=?", (job,))
    assert client.post('/api/actions', json={'job_id': job, 'suggestion_index': 0}).status_code == 409
