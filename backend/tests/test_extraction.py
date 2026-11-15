from copy import deepcopy
from pathlib import Path
import json
import time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import httpx
import pytest
from app.main import create_app
from app.extraction import GeminiProvider, ProviderError, MAX_VIDEO, connect, run_batch, run_one

CAPTION = 'Practice SQLite joins. Apply tomorrow.'
RESULT = {'summary': 'Practice joins before applying.', 'topics': ['SQLite'],
          'suggestions': [{'text': 'Practice joins', 'source_index': 0}],
          'date_candidates': [{'original_text': 'tomorrow', 'source_index': 0}],
          'sources': [{'excerpt': CAPTION, 'origin': 'caption', 'timestamp_seconds': None}]}
CLIP = (Path(__file__).parent / 'fixtures' / 'blue.mp4').read_bytes()

class Provider:
    def __init__(self, error=None, video=False):
        self.error, self.video, self.calls, self.paths = error, video, 0, []
    def extract(self, caption, video_path, mime):
        self.calls += 1
        if video_path:
            self.paths.append(video_path)
            assert video_path.exists()
        if self.error: raise self.error
        result = deepcopy(RESULT)
        if self.video: result['sources'][0].update(origin='video', timestamp_seconds=1.0)
        return result

class BatchProvider(Provider):
    def __init__(self, error=None, results=None):
        super().__init__(error)
        self.results, self.batch_calls = results, 0
    def extract_batch(self, captions):
        self.batch_calls += 1
        if self.error: raise self.error
        return deepcopy(self.results) if self.results is not None else [deepcopy(RESULT) for _ in captions]

@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / 'revero.db'
    with TestClient(create_app(path)) as client:
        reel = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/Extract/'}).json()
        yield client, path, reel['id']

def add(client, rid, **kwargs):
    return client.post(f'/api/reels/{rid}/content', data={'caption': CAPTION}, **kwargs)

def test_caption_cached_restart_and_revision(inbox):
    client, path, rid = inbox
    job = add(client, rid).json()
    assert job['state'] == 'queued'
    provider = Provider()
    assert run_one(path, provider)
    assert not run_one(path, provider)
    content = client.get(f'/api/reels/{rid}/content').json()
    assert content['reel']['status'] == 'ready'
    assert content['job']['caption_only']
    assert content['job']['takeaway'] == RESULT
    assert add(client, rid).json()['id'] == job['id']
    assert not run_one(path, provider)
    assert provider.calls == 1
    with TestClient(create_app(path)) as restarted:
        assert restarted.get(f'/api/reels/{rid}/content').json()['job']['takeaway'] == RESULT
    different = client.post(f'/api/reels/{rid}/content', data={'caption': 'Another caption'}).json()
    assert different['id'] != job['id']

def test_video_cleanup_and_retry(inbox):
    client, path, rid = inbox
    job = add(client, rid, files={'video': ('clip.mp4', CLIP, 'video/mp4')}).json()
    failing = Provider(ProviderError('Try again'))
    run_one(path, failing)
    assert all(not p.exists() for p in failing.paths)
    assert client.get(f'/api/reels/{rid}/content').json()['job']['state'] == 'failed'
    assert client.post(f'/api/reels/{rid}/retry').json()['id'] == job['id']
    success = Provider(video=True)
    run_one(path, success)
    assert all(not p.exists() for p in success.paths)
    result = client.get(f'/api/reels/{rid}/content').json()['job']
    assert result['state'] == 'ready' and not result['caption_only']
    with connect(path) as db:
        assert db.execute('SELECT media FROM extraction_jobs').fetchone()['media'] is None

@pytest.mark.parametrize('error, delay', [(ProviderError('Temporary', transient=True), 5), (ProviderError('Quota', quota=True), 5)])
def test_backoff_and_quota(inbox, error, delay, monkeypatch):
    monkeypatch.setattr('app.extraction.random.uniform', lambda a, b: 0)
    client, path, rid = inbox
    add(client, rid)
    provider = Provider(error)
    run_one(path, provider, now=100)
    job = client.get(f'/api/reels/{rid}/content').json()['job']
    assert job['state'] == 'queued' and job['available_at'] == 100 + delay
    assert not run_one(path, provider, now=101)
    assert run_one(path, Provider(), now=100 + delay)

def test_quota_retry_after_and_short_circuit(inbox, monkeypatch):
    monkeypatch.setattr('app.extraction.random.uniform', lambda a, b: 0)
    client, path, rid = inbox
    add(client, rid)
    run_one(path, Provider(ProviderError('Quota', quota=True, retry_after=120)), now=100)
    job = client.get(f'/api/reels/{rid}/content').json()['job']
    assert job['state'] == 'queued' and job['available_at'] == 220
    # The circuit breaker pauses the whole queue briefly, but expires before the job's own backoff.
    assert not run_one(path, Provider(), now=159)
    assert not run_one(path, Provider(), now=219)  # Job's own backoff still applies.
    assert run_one(path, Provider(), now=220)

def test_retry_limit_and_deferred_retry_guard(inbox, monkeypatch):
    monkeypatch.setattr('app.extraction.random.uniform', lambda a, b: 0)
    client, path, rid = inbox
    add(client, rid)
    now = time.time()
    provider = Provider(ProviderError('Temporary', transient=True))
    for offset in (0, 5, 15, 35):
        assert run_one(path, provider, now=now + offset)
        if offset == 0: assert client.post(f'/api/reels/{rid}/retry').status_code == 409
    assert client.get(f'/api/reels/{rid}/content').json()['job']['state'] == 'failed'
    assert client.post(f'/api/reels/{rid}/retry').json()['state'] == 'queued'

def test_token_bucket_rpm_refills_and_persists(inbox):
    client, path, rid = inbox
    add(client, rid)
    other = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/Second/'}).json()
    add(client, other['id'])
    limits = {'rpm': 1, 'rpd': 100, 'batch': 1, 'max_attempts': 4}
    assert run_one(path, Provider(), now=100, limits=limits)
    assert not run_one(path, Provider(), now=100, limits=limits)  # Minute bucket empty.
    with connect(path) as db:
        rate = db.execute('SELECT tokens, day_count FROM extraction_rate WHERE id=1').fetchone()
        assert rate['tokens'] == 0 and rate['day_count'] == 1
    # Refill is persisted in SQLite, so a restart does not reset the budget.
    assert run_one(path, Provider(), now=161, limits=limits)

def test_token_bucket_daily_cap_and_utc_rollover(inbox):
    client, path, rid = inbox
    add(client, rid)
    other = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/Second/'}).json()
    add(client, other['id'])
    limits = {'rpm': 100, 'rpd': 1, 'batch': 1, 'max_attempts': 4}
    assert run_one(path, Provider(), now=100, limits=limits)
    assert not run_one(path, Provider(), now=110, limits=limits)  # Daily cap reached.
    assert run_one(path, Provider(), now=100 + 86400, limits=limits)  # New UTC day resets the count.

def test_process_now_resets_backoff_and_prioritizes(inbox, monkeypatch):
    monkeypatch.setattr('app.extraction.random.uniform', lambda a, b: 0)
    client, path, rid = inbox
    add(client, rid)
    run_one(path, Provider(ProviderError('Temporary', transient=True)), now=100)
    assert client.get(f'/api/reels/{rid}/content').json()['job']['state'] == 'queued'
    result = client.post(f'/api/reels/{rid}/process')
    assert result.status_code == 200 and result.json()['state'] == 'queued'
    with connect(path) as db:
        job = db.execute('SELECT attempts, available_at, priority FROM extraction_jobs').fetchone()
        assert job['attempts'] == 0 and job['available_at'] == 0 and job['priority'] == 1
    # The override skips backoff but still needs a rate-limit token.
    assert run_one(path, Provider(), now=101)
    assert client.get(f'/api/reels/{rid}/content').json()['job']['state'] == 'ready'

def queue_caption_jobs(client, rid, count):
    ids = [rid]
    for index in range(count - 1):
        other = client.post('/api/reels', json={'url': f'https://www.instagram.com/reel/Batch{index}/'}).json()
        ids.append(other['id'])
    for identifier in ids:
        add(client, identifier)
    return ids

def test_batch_claims_and_processes_caption_jobs_in_one_call(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 3)
    provider = BatchProvider()
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    assert run_batch(path, provider, now=100, limits=limits) == 3
    assert provider.batch_calls == 1 and provider.calls == 0
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM extraction_jobs WHERE state='ready'").fetchone()[0] == 3

def test_batch_count_mismatch_falls_back_to_isolated_calls(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 3)
    provider = BatchProvider(results=[deepcopy(RESULT)])  # Wrong count for three inputs.
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    assert run_batch(path, provider, now=100, limits=limits) == 3
    assert provider.batch_calls == 1 and provider.calls == 3
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM extraction_jobs WHERE state='ready'").fetchone()[0] == 3

def test_batch_invalid_item_falls_back_and_still_succeeds(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 3)
    invalid = deepcopy(RESULT)
    invalid['sources'][0]['excerpt'] = 'Invented evidence'
    provider = BatchProvider(results=[invalid, deepcopy(RESULT), deepcopy(RESULT)])
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    assert run_batch(path, provider, now=100, limits=limits) == 3
    assert provider.batch_calls == 1 and provider.calls == 3
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM extraction_jobs WHERE state='ready'").fetchone()[0] == 3

def test_batch_quota_error_defers_without_extra_calls(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 3)
    provider = BatchProvider(error=ProviderError('Quota', quota=True))
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    assert run_batch(path, provider, now=100, limits=limits) == 3
    assert provider.batch_calls == 1 and provider.calls == 0
    with connect(path) as db:
        states = {row[0] for row in db.execute('SELECT state FROM extraction_jobs')}
        assert states == {'queued'}

def test_batch_respects_batch_size_and_token_bucket(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 3)
    provider = BatchProvider()
    limits = {'rpm': 10, 'rpd': 100, 'batch': 2, 'max_attempts': 4}
    assert run_batch(path, provider, now=100, limits=limits) == 2
    assert run_batch(path, provider, now=101, limits=limits) == 1
    assert provider.batch_calls == 2

def test_batch_leaves_video_jobs_for_the_single_path(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 2)
    video_reel = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/BatchVideo/'}).json()
    add(client, video_reel['id'], files={'video': ('clip.mp4', CLIP, 'video/mp4')})
    provider = BatchProvider()
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    assert run_batch(path, provider, now=100, limits=limits) == 2
    with connect(path) as db:
        assert db.execute('SELECT state FROM extraction_jobs WHERE reel_id=?', (video_reel['id'],)).fetchone()[0] == 'queued'
    assert run_one(path, provider, now=101, limits=limits)
    with connect(path) as db:
        assert db.execute('SELECT state FROM extraction_jobs WHERE reel_id=?', (video_reel['id'],)).fetchone()[0] == 'ready'

class EchoBatchProvider:
    def __init__(self, reverse=False):
        self.reverse, self.batch_calls, self.calls = reverse, 0, 0
    @staticmethod
    def result(caption):
        result = deepcopy(RESULT)
        result['sources'][0]['excerpt'] = caption
        result['suggestions'][0]['source_index'] = 0
        result['date_candidates'] = []
        return result
    def extract_batch(self, captions):
        self.batch_calls += 1
        order = list(reversed(captions)) if self.reverse else captions
        return [self.result(caption) for caption in order]
    def extract(self, caption, video_path, mime):
        self.calls += 1
        return self.result(caption)


def test_batch_maps_each_result_to_its_own_caption(inbox):
    client, path, rid = inbox
    captions = ['Practice joins today.', 'Practice indexes tomorrow.', 'Practice plans weekly.']
    ids = [rid]
    for index in range(1, len(captions)):
        ids.append(client.post('/api/reels', json={'url': f'https://www.instagram.com/reel/Map{index}/'}).json()['id'])
    for identifier, caption in zip(ids, captions):
        client.post(f'/api/reels/{identifier}/content', data={'caption': caption})
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    provider = EchoBatchProvider()
    assert run_batch(path, provider, now=100, limits=limits) == 3
    assert provider.batch_calls == 1 and provider.calls == 0
    for identifier, caption in zip(ids, captions):
        takeaway = client.get(f'/api/reels/{identifier}/content').json()['job']['takeaway']
        assert takeaway['sources'][0]['excerpt'] == caption

def test_batch_misordered_results_fall_back_to_correct_mapping(inbox):
    client, path, rid = inbox
    captions = ['Practice joins today.', 'Practice indexes tomorrow.']
    other = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/MapReverse/'}).json()['id']
    for identifier, caption in zip([rid, other], captions):
        client.post(f'/api/reels/{identifier}/content', data={'caption': caption})
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    provider = EchoBatchProvider(reverse=True)
    assert run_batch(path, provider, now=100, limits=limits) == 2
    assert provider.batch_calls == 1 and provider.calls == 2
    for identifier, caption in zip([rid, other], captions):
        takeaway = client.get(f'/api/reels/{identifier}/content').json()['job']['takeaway']
        assert takeaway['sources'][0]['excerpt'] == caption

def test_batch_single_claim_with_concurrent_workers(inbox):
    client, path, rid = inbox
    queue_caption_jobs(client, rid, 3)
    provider = BatchProvider()
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: run_batch(path, provider, now=100, limits=limits), range(4)))
    assert sum(outcomes) == 3 and provider.batch_calls == 1
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM extraction_jobs WHERE state='ready'").fetchone()[0] == 3

def test_batch_recovers_expired_lease(inbox):
    client, path, rid = inbox
    ids = queue_caption_jobs(client, rid, 2)
    with connect(path) as db:
        db.execute("UPDATE extraction_jobs SET state='processing', lease_until=1")
    provider = BatchProvider()
    limits = {'rpm': 10, 'rpd': 100, 'batch': 5, 'max_attempts': 4}
    assert run_batch(path, provider, now=2, limits=limits) == 2
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM extraction_jobs WHERE state='ready'").fetchone()[0] == 2

def test_lease_recovery_and_latest_revision(inbox):
    client, path, rid = inbox
    old = add(client, rid).json()
    with connect(path) as db:
        db.execute("UPDATE extraction_jobs SET state='processing', lease_until=1 WHERE id=?", (old['id'],))
    assert run_one(path, Provider(), now=2)
    newest = client.post(f'/api/reels/{rid}/content', data={'caption': CAPTION + ' New revision.'}).json()
    with connect(path) as db:
        db.execute("UPDATE extraction_jobs SET state='queued' WHERE id=?", (old['id'],))
    assert run_one(path, Provider())
    assert client.get(f'/api/reels/{rid}/content').json()['job']['id'] == newest['id']
    assert not run_one(path, Provider())

def test_single_claim_with_concurrent_workers(inbox):
    client, path, rid = inbox
    add(client, rid)
    provider = Provider()
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: run_one(path, provider), range(4)))
    assert sum(outcomes) == 1 and provider.calls == 1

@pytest.mark.parametrize('change', ['invented excerpt', 'video origin', 'caption timestamp', 'bad source', 'invented date', 'no sources'])
def test_bad_evidence_not_persisted(inbox, change):
    client, path, rid = inbox
    add(client, rid)
    raw = deepcopy(RESULT)
    if change == 'invented excerpt': raw['sources'][0]['excerpt'] = 'Made up'
    if change == 'video origin': raw['sources'][0]['origin'] = 'video'
    if change == 'caption timestamp': raw['sources'][0]['timestamp_seconds'] = 10
    if change == 'bad source': raw['suggestions'][0]['source_index'] = 4
    if change == 'invented date': raw['date_candidates'][0]['original_text'] = 'next year'
    if change == 'no sources': raw['sources'] = []
    class InvalidProvider:
        def extract(self, *args): return raw
    run_one(path, InvalidProvider())
    job = client.get(f'/api/reels/{rid}/content').json()['job']
    assert job['state'] == 'failed' and job['takeaway'] is None
    assert client.get('/api/reels').json()[0]['url'].endswith('/Extract/')

def test_upload_limits_and_missing_content(inbox):
    client, path, rid = inbox
    url = f'/api/reels/{rid}/content'
    assert client.post(url, data={'caption': ''}).status_code == 400
    assert client.post(url, data={'caption': 'a' * 20001}).status_code == 400
    assert client.post(url, files={'video': ('bad.mp4', b'not video', 'video/mp4')}).status_code == 400
    assert client.post(url, files={'video': ('bad.txt', CLIP, 'text/plain')}).status_code == 400
    assert client.post(url, files={'video': ('large.mp4', CLIP + b'0' * MAX_VIDEO, 'video/mp4')}).status_code == 413
    assert add(client, 999).status_code == 404
    assert client.get('/api/reels/999/content').status_code == 404
    assert client.post(f'/api/reels/{rid}/retry').status_code == 404
    assert client.get('/api/reels').json()[0]['status'] == 'needs_content'

def test_gemini_transport_and_structured_schema(monkeypatch):
    monkeypatch.setattr('app.extraction.settings', lambda: {'GEMINI_MODEL': 'test-model', 'GEMINI_API_KEY': 'test-key'})
    def post(url, **kwargs):
        assert url.endswith('/test-model:generateContent')
        assert kwargs['headers']['x-goog-api-key'] == 'test-key'
        assert kwargs['json']['generationConfig']['responseJsonSchema']['properties']['sources']
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': json.dumps(RESULT)}]}}]})
    monkeypatch.setattr('app.extraction.httpx.post', post)
    assert GeminiProvider().extract(CAPTION, None, None) == RESULT
    monkeypatch.setattr('app.extraction.httpx.post', lambda *a, **k: httpx.Response(429))
    with pytest.raises(ProviderError) as error: GeminiProvider().extract(CAPTION, None, None)
    assert error.value.quota


def test_gemini_batch_uses_object_wrapped_schema_and_returns_items(monkeypatch):
    monkeypatch.setattr('app.extraction.settings', lambda: {'GEMINI_MODEL': 'test-model', 'GEMINI_API_KEY': 'test-key'})
    def post(url, **kwargs):
        schema = kwargs['json']['generationConfig']['responseJsonSchema']
        assert schema['type'] == 'object'
        assert schema['properties']['items']['type'] == 'array'
        assert schema['properties']['items']['items']['properties']['sources']
        # Shared $defs must live at the root so nested $ref paths resolve.
        assert 'WalkthroughStep' in schema['$defs']
        assert '$defs' not in schema['properties']['items']['items']
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': json.dumps({'items': [RESULT, RESULT]})}]}}]})
    monkeypatch.setattr('app.extraction.httpx.post', post)
    assert GeminiProvider().extract_batch([CAPTION, CAPTION]) == [RESULT, RESULT]


def test_media_expiry_and_global_quota(inbox):
    from app.extraction import cleanup_media
    client, path, rid = inbox
    add(client, rid, files={'video': ('clip.mp4', CLIP, 'video/mp4')})
    cleanup_media(path, now=time.time() + 86401)
    job = client.get(f'/api/reels/{rid}/content').json()['job']
    assert job['state'] == 'failed'
    assert 'expired' in job['error']
    # Reattach restores the same job identity and its media for a manual retry.
    restored = add(client, rid, files={'video': ('clip.mp4', CLIP, 'video/mp4')}).json()
    assert restored['id'] == job['id']
    client.post(f'/api/reels/{rid}/retry')
    run_one(path, Provider(ProviderError('Quota', quota=True, retry_after=300)), now=100)
    other = client.post('/api/reels', json={'url': 'https://www.instagram.com/reel/Other/'}).json()
    add(client, other['id'])
    assert not run_one(path, Provider(), now=120)  # Short circuit breaker blocks the queue.
    assert run_one(path, Provider(), now=200)  # Circuit expires; the deferred job keeps its own backoff.


def test_existing_milestone_one_database_migrates(tmp_path):
    import sqlite3
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE reels (id INTEGER PRIMARY KEY, shortcode TEXT UNIQUE, url TEXT, status TEXT, created_at TEXT)')
        db.execute("INSERT INTO reels VALUES (1, 'Before', 'https://www.instagram.com/reel/Before/', 'needs_content', '2026-01-01')")
    with TestClient(create_app(path)) as client:
        row = client.get('/api/reels').json()[0]
        assert row['id'] == 1 and row['shortcode'] == 'Before' and row['active_job'] is None
        assert add(client, 1).status_code == 200


def test_config_does_not_expose_credentials(inbox, monkeypatch):
    client, _, _ = inbox
    monkeypatch.setattr('app.extraction.settings', lambda: {'GEMINI_API_KEY': 'secret', 'GEMINI_MODEL': 'test-model', 'GEMINI_FREE_TIER_CONFIRMED': 'true'})
    response = client.get('/api/processing')
    assert response.json()['configured'] is True
    assert 'secret' not in response.text
    monkeypatch.setattr('app.extraction.settings', lambda: {'GEMINI_API_KEY': 'secret', 'GEMINI_MODEL': 'test-model', 'GEMINI_FREE_TIER_CONFIRMED': 'false'})
    assert client.get('/api/processing').json()['configured'] is False
