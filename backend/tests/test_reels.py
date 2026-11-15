from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest
from app.main import create_app


def test_save_duplicate_restart(tmp_path):
    path = tmp_path / 'reels.sqlite3'
    with TestClient(create_app(path)) as client:
        first = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/AbC123/?igsh=one'}).json()
        assert first['created'] is True
        assert first['status'] == 'needs_content'
        assert first['url'] == 'https://www.instagram.com/reel/AbC123/'
        duplicate = client.post('/api/reels', json={'url': 'https://instagram.com/reel/AbC123?igsh=two#fragment'}).json()
        assert duplicate == {**first, 'created': False}
        lower = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/abc123/'}).json()
        assert lower['id'] != first['id']
    with TestClient(create_app(path)) as restarted:
        rows = restarted.get('/api/reels').json()
        assert [row['id'] for row in rows] == [first['id'], lower['id']]


@pytest.mark.parametrize('url', [
    'https://example.com/reel/AbC123/', 'http://www.instagram.com/reel/AbC123/',
    'https://www.instagram.com.evil.com/reel/AbC123/',
    'https://user@www.instagram.com/reel/AbC123/',
    'https://www.instagram.com:443/reel/AbC123/',
    'https://www.instagram.com/p/AbC123/', 'https://www.instagram.com/reel/',
    'https://www.instagram.com/reel/abc/extra/',
    'https://www.instagram.com/reel/a%20b/', '',
    'https://www.instagram.com/reel/ab\nc/', 'https://[broken/reel/abc/',
])
def test_invalid(tmp_path, url):
    with TestClient(create_app(tmp_path / 'db')) as client:
        assert client.post('/api/reels', json={'url': url}).status_code == 400
        assert client.get('/api/reels').json() == []


def test_concurrent_duplicates(tmp_path):
    with TestClient(create_app(tmp_path / 'db')) as client:
        def save(_):
            return client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/Same/'}).json()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(save, range(8)))
        assert sum(row['created'] for row in results) == 1
        assert len({row['id'] for row in results}) == 1
