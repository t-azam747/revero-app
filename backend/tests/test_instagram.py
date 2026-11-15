from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import copy
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.extraction import attach, backfill_titles
from app.instagram import Config, InstagramSender, MAX_BODY, connect, initialize, intake, run_one
from app.instagram_webhook import create_app
from app.main import create_app as private_app

CFG = Config('dummy-secret', 'dummy-verify', '100', '200', 'dummy-access-token', 'v25.0', True)


def fixture(mid='m1', provider='300', url='https://cdn.example.test/reference'):
    return {'object': 'instagram', 'entry': [{'id': '100', 'messaging': [{
        'sender': {'id': '200'}, 'recipient': {'id': '100'}, 'timestamp': int(time.time()*1000),
        'message': {'mid': mid, 'attachments': [{'type': 'ig_reel', 'payload': {
            'reel_video_id': provider, 'url': url, 'title': 'Authored fixture only'}}]}}]}]}


def post(client, payload, body=None):
    raw = json.dumps(payload, indent=2).encode() if body is None else body
    sig = hmac.new(CFG.app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post('/webhooks/instagram', content=raw, headers={'X-Hub-Signature-256': 'sha256='+sig})


def counts(path):
    with connect(path) as db:
        return tuple(db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
                     ('reels', 'instagram_inbound', 'instagram_outbox'))


def test_migrates_legacy_outbox_without_kind_column(tmp_path):
    import sqlite3
    path = tmp_path/'db'
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE instagram_outbox (
            id INTEGER PRIMARY KEY, inbound_id INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
            lease_until REAL, attempt_id TEXT, provider_mid TEXT, error TEXT)''')
    initialize(path)  # Must add kind/text before creating the unique index.
    with connect(path) as db:
        columns = {row['name'] for row in db.execute('PRAGMA table_info(instagram_outbox)')}
        assert {'kind', 'text'} <= columns
        assert db.execute("SELECT name FROM sqlite_master WHERE name='idx_instagram_outbox_inbound_kind'").fetchone()


def test_handshake_and_isolation(tmp_path):
    with TestClient(create_app(tmp_path/'db', config=CFG)) as client:
        params = {'hub.mode': 'subscribe', 'hub.verify_token': CFG.verify_token, 'hub.challenge': '12345'}
        r = client.get('/webhooks/instagram', params=params)
        assert r.status_code == 200 and r.text == '12345' and r.headers['content-type'].startswith('text/plain')
        for key in ('hub.mode', 'hub.verify_token', 'hub.challenge'):
            assert client.get('/webhooks/instagram', params={**params, key: ''}).status_code == 403
        for route in ('/api/reels', '/api/digest', '/docs', '/openapi.json', '/'):
            assert client.get(route).status_code == 404


def test_signed_replay_concurrent_restart_and_reply(tmp_path, caplog):
    path = tmp_path/'db'
    with TestClient(create_app(path, config=CFG)) as client:
        with ThreadPoolExecutor(max_workers=5) as pool:
            assert all(r.status_code == 200 for r in pool.map(lambda _: post(client, fixture()), range(10)))
        assert counts(path) == (1, 1, 1)
        with connect(path) as db:
            assert db.execute('SELECT url FROM reels').fetchone()[0] == ''
            assert db.execute('SELECT reference FROM instagram_shares').fetchone()[0].startswith('https://cdn.')
    with TestClient(create_app(path, config=CFG)) as client:
        assert post(client, fixture()).status_code == 200
        assert counts(path) == (1, 1, 1)
    requests = []
    def send(request):
        requests.append(request)
        assert str(request.url) == 'https://graph.instagram.com/v25.0/100/messages'
        assert request.headers['authorization'] == 'Bearer dummy-access-token'
        assert json.loads(request.content) == {'recipient': {'id': '200'}, 'message': {'text': 'Saved'}}
        return httpx.Response(200, json={'recipient_id': '200', 'message_id': 'reply1'})
    sender = InstagramSender(CFG, httpx.MockTransport(send))
    assert run_one(path, CFG, sender)
    assert not run_one(path, CFG, sender)
    assert len(requests) == 1
    with TestClient(private_app(path)) as client:
        assert len(client.get('/api/reels').json()) == 1
    assert all(secret not in caplog.text for secret in ('dummy-access-token', 'dummy-secret', 'cdn.example', 'Authored fixture'))


def test_signature_size_json(tmp_path):
    path = tmp_path/'db'
    with TestClient(create_app(path, config=CFG)) as client:
        assert client.post('/webhooks/instagram', content=b'bad').status_code == 403
        for sig in ('sha256=bad', 'sha256='+'0'*64):
            assert client.post('/webhooks/instagram', content=b'{', headers={'X-Hub-Signature-256': sig}).status_code == 403
        assert post(client, {}, body=b'{').status_code == 400
        assert post(client, {}, body=b' '* (MAX_BODY+1)).status_code == 413
        raw = json.dumps(fixture()).encode()
        sig = hmac.new(CFG.app_secret.encode(), raw, hashlib.sha256).hexdigest()
        assert client.post('/webhooks/instagram', content=raw+b' ', headers={'X-Hub-Signature-256': 'sha256='+sig}).status_code == 403
        for payload in ([], None, 'bad', {'object': 'instagram', 'entry': [None, {'id': '100', 'messaging': [None]}]}):
            assert post(client, payload).status_code == 200
        assert counts(path) == (0, 0, 0)


@pytest.mark.parametrize('change', ['echo', 'deleted', 'unsupported', 'account', 'sender', 'type', 'recipient'])
def test_ignore_events(tmp_path, change):
    path = tmp_path/'db'; payload = fixture(); event = payload['entry'][0]['messaging'][0]
    if change in ('echo', 'deleted', 'unsupported'):
        event['message']['is_'+change] = True
    elif change == 'account': payload['entry'][0]['id'] = '999'
    elif change in ('sender', 'recipient'): event[change]['id'] = '999'
    else: event['message']['attachments'][0]['type'] = 'image'
    with TestClient(create_app(path, config=CFG)) as client:
        assert post(client, payload).status_code == 200
        assert counts(path) == (0, 0, 0)


def test_batch_manual_and_provider_dedupe(tmp_path):
    path = tmp_path/'db'
    with TestClient(private_app(path)) as client:
        first = client.post('/api/reels', json={'url': 'https://instagram.com/reel/AbC/?a=1'}).json()
    with TestClient(create_app(path, config=CFG)) as client:
        payload = fixture(url='https://www.instagram.com/reel/AbC/')
        payload['entry'] += fixture('m2', '300', 'https://cdn.example.test/changed')['entry']
        payload['entry'] += fixture('m3', '301', 'https://instagram.com/reel/AbC/?x=1')['entry']
        assert post(client, payload).status_code == 200
        assert counts(path) == (1, 3, 3)
        with connect(path) as db:
            assert {r[0] for r in db.execute('SELECT reel_id FROM instagram_shares')} == {first['id']}


def test_plain_dm_bootstrap_and_text_link(tmp_path):
    path = tmp_path/'db'; initialize(path)
    payload = fixture(); event = payload['entry'][0]['messaging'][0]
    event['message'] = {'mid': 'plain', 'text': 'Hello private content'}
    intake(path, payload, replace(CFG, sender_id=''))
    assert counts(path) == (0, 0, 0)
    with connect(path) as db:
        assert db.execute('SELECT sender_id FROM instagram_senders').fetchone()[0] == '200'
    intake(path, payload, CFG)
    assert counts(path) == (0, 1, 0)  # A greeting is received, never falsely acknowledged as a saved Reel.
    event['message'] = {'mid': 'link', 'text': 'https://instagram.com/reel/TextLink/'}
    intake(path, payload, CFG)
    assert counts(path) == (1, 2, 1)


@pytest.mark.parametrize('mode,expected', [('timeout','uncertain'), ('500','uncertain'), ('429','queued'), ('401','failed'), ('bad','uncertain'), ('connect','queued')])
def test_send_failures(tmp_path, mode, expected):
    path = tmp_path/'db'; initialize(path); intake(path, fixture(), CFG)
    calls = []
    def send(request):
        calls.append(1)
        if mode == 'timeout': raise httpx.ReadTimeout('PRIVATE TOKEN MUST NOT LEAK')
        if mode == 'connect': raise httpx.ConnectError('PRIVATE TOKEN MUST NOT LEAK')
        return httpx.Response(200 if mode == 'bad' else int(mode), json={'private': 'PRIVATE TOKEN MUST NOT LEAK'})
    sender = InstagramSender(CFG, httpx.MockTransport(send))
    assert run_one(path, CFG, sender)
    assert not run_one(path, CFG, sender)
    with connect(path) as db:
        row = db.execute('SELECT * FROM instagram_outbox').fetchone()
        assert row['state'] == expected and 'PRIVATE' not in row['error']
    assert len(calls) == 1


def test_disabled_expired_interrupted_and_atomicity(tmp_path):
    path = tmp_path/'db'; initialize(path); intake(path, fixture(), CFG)
    assert not run_one(path, replace(CFG, replies_enabled=False))
    assert run_one(path, CFG, now=time.time()+86401)
    with connect(path) as db:
        assert db.execute('SELECT state FROM instagram_outbox').fetchone()[0] == 'expired'
        db.execute("CREATE TRIGGER fail_reply BEFORE INSERT ON instagram_outbox BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
    with pytest.raises(Exception, match='fixture rollback'):
        intake(path, fixture('new', 'new'), CFG)
    assert counts(path) == (1, 1, 1)
    with connect(path) as db:
        db.execute("UPDATE instagram_outbox SET state='sending',lease_until=0")
    assert not run_one(path, CFG)
    with connect(path) as db:
        assert db.execute('SELECT state FROM instagram_outbox').fetchone()[0] == 'uncertain'


def test_canonical_enrichment_and_reference_only_limits(tmp_path):
    path = tmp_path/'db'; initialize(path)
    intake(path, fixture(), CFG)
    intake(path, fixture('newmid', '300', 'https://instagram.com/reel/Enriched/'), CFG)
    with connect(path) as db:
        assert db.execute('SELECT url FROM reels').fetchone()[0] == 'https://www.instagram.com/reel/Enriched/'
    with TestClient(private_app(path)) as client:
        saved = client.post('/api/reels', json={'url':'https://instagram.com/reel/Enriched/?again=1'}).json()
        assert saved['created'] is False
    payload = fixture('bad', None)
    payload['entry'][0]['messaging'][0]['message']['attachments'] += [{'type': [], 'payload': []}]
    intake(path, payload, CFG)
    assert counts(path) == (1, 2, 2)  # Non-permalink URL without a Reel ID cannot fabricate a save.


def test_only_one_worker_claims_and_retry_after_delay(tmp_path):
    path = tmp_path/'db'; initialize(path); intake(path, fixture(), CFG)
    calls = []
    class Sender:
        def send(self, recipient):
            calls.append(recipient)
            time.sleep(.05)
            return 'reply'
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: run_one(path, CFG, Sender()), range(4))) == 1
    assert calls == ['200']
    intake(path, fixture('retry'), CFG)
    now = time.time()
    bad = InstagramSender(CFG, httpx.MockTransport(lambda _: httpx.Response(429)))
    assert run_one(path, CFG, bad, now=now)
    assert not run_one(path, CFG, Sender(), now=now+299)
    assert run_one(path, CFG, Sender(), now=now+301)
    assert calls == ['200', '200']


def test_provider_reference_enrichment_merges_manual_save_without_losing_jobs(tmp_path):
    from app.extraction import attach
    path = tmp_path/'db'; initialize(path)
    intake(path, fixture(), CFG)
    with connect(path) as db:
        provider_reel = db.execute('SELECT id FROM reels').fetchone()[0]
    original_job = attach(path, provider_reel, 'Authored source caption')
    with TestClient(private_app(path)) as client:
        manual = client.post('/api/reels', json={'url':'https://instagram.com/reel/LaterKnown/'}).json()
    attach(path, manual['id'], 'Authored source caption')  # Same revision in both saves.
    intake(path, fixture('enrich', '300', 'https://instagram.com/reel/LaterKnown/'), CFG)
    assert counts(path) == (1, 2, 2)
    with connect(path) as db:
        assert {r[0] for r in db.execute('SELECT reel_id FROM instagram_shares')} == {manual['id']}
        assert {r[0] for r in db.execute('SELECT reel_id FROM extraction_jobs')} == {manual['id']}
        assert db.execute('SELECT id FROM extraction_jobs WHERE id=?', (original_job['id'],)).fetchone()
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_local_admin_redaction_and_uncertain_resolution(tmp_path, monkeypatch, capsys):
    from app import instagram_admin
    import sys
    path = tmp_path/'db'; initialize(path); intake(path, fixture(), CFG)
    with connect(path) as db:
        db.execute("UPDATE instagram_outbox SET state='uncertain'")
    monkeypatch.setattr(instagram_admin, 'DEFAULT_DB', path)
    monkeypatch.setattr(sys, 'argv', ['admin', '--resolve', '1', '--outcome', 'delivered'])
    instagram_admin.main()
    report = capsys.readouterr().out
    parsed = json.loads(report)
    assert parsed['outbox'][0]['state'] == 'sent'
    assert parsed['shares'][0]['access_class'] == 'unmeasured'
    assert all(secret not in report for secret in ('cdn.example', 'Authored fixture', 'dummy-secret', 'dummy-access-token'))
    assert not run_one(path, CFG)


def test_unified_login_routes_credentials_only_to_facebook_host():
    cfg = replace(CFG, login_flow='unified')
    requests = []
    def send(request):
        requests.append(request)
        assert str(request.url) == 'https://graph.facebook.com/v25.0/100/messages'
        assert request.headers['Authorization'] == 'Bearer dummy-access-token'
        assert 'dummy-access-token' not in str(request.url)
        return httpx.Response(200, json={'message_id':'unified-reply'})
    assert InstagramSender(cfg,httpx.MockTransport(send)).send('200') == 'unified-reply'
    assert len(requests) == 1
    with pytest.raises(ValueError, match='Unsupported'):
        _ = replace(CFG, login_flow='https://untrusted.example').api_host
    assert CFG.api_host == 'graph.instagram.com'


def test_titled_share_queues_caption_job_and_replay_deduplicates(tmp_path):
    path = tmp_path/'db'; initialize(path)
    intake(path, fixture(), CFG)
    with connect(path) as db:
        job = db.execute('SELECT * FROM extraction_jobs').fetchone()
        reel = db.execute('SELECT active_job, status FROM reels').fetchone()
        assert job['caption'] == 'Authored fixture only'
        assert job['state'] == 'queued' and job['mime'] is None and job['media'] is None
        assert reel['active_job'] == job['id'] and reel['status'] == 'queued'
    intake(path, fixture(), CFG)  # Replay creates neither a second share nor a second job.
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM extraction_jobs').fetchone()[0] == 1
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_untitled_share_stays_needs_content(tmp_path):
    path = tmp_path/'db'; initialize(path)
    payload = fixture()
    del payload['entry'][0]['messaging'][0]['message']['attachments'][0]['payload']['title']
    intake(path, payload, CFG)
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM extraction_jobs').fetchone()[0] == 0
        assert db.execute('SELECT status FROM reels').fetchone()[0] == 'needs_content'


def test_new_titled_share_does_not_overwrite_manual_content(tmp_path):
    path = tmp_path/'db'; initialize(path)
    with TestClient(private_app(path)) as client:
        reel = client.post('/api/reels', json={'url': 'https://instagram.com/reel/Manual/'}).json()
    manual = attach(path, reel['id'], 'Manually supplied caption')
    intake(path, fixture('manual-share', '800', 'https://instagram.com/reel/Manual/'), CFG)
    with connect(path) as db:
        assert db.execute('SELECT active_job FROM reels WHERE id=?', (reel['id'],)).fetchone()[0] == manual['id']
        assert db.execute('SELECT count(*) FROM extraction_jobs').fetchone()[0] == 1


def test_backfill_titles_is_idempotent_and_uses_same_job_path(tmp_path):
    path = tmp_path/'db'; initialize(path)
    with connect(path) as db:
        db.execute("INSERT INTO reels(shortcode,url) VALUES('OldShare','https://www.instagram.com/reel/OldShare/')")
        reel_id = db.execute("SELECT id FROM reels WHERE shortcode='OldShare'").fetchone()[0]
        db.execute('''INSERT INTO instagram_inbound(account_id,mid,sender_id,event_at,received_at,kind)
                      VALUES('100','old-mid','200',0,0,'reel')''')
        inbound_id = db.execute("SELECT id FROM instagram_inbound WHERE mid='old-mid'").fetchone()[0]
        db.execute('''INSERT INTO instagram_shares(inbound_id,position,reel_id,attachment_type,provider_id,reference,title)
                      VALUES(?,0,?,'ig_reel','900','https://cdn.example.test/old','Backfilled caption')''',
                   (inbound_id, reel_id))
    assert backfill_titles(path) == 1
    with connect(path) as db:
        job = db.execute('SELECT * FROM extraction_jobs').fetchone()
        assert job['reel_id'] == reel_id and job['caption'] == 'Backfilled caption' and job['state'] == 'queued'
        reel = db.execute('SELECT active_job, status FROM reels WHERE id=?', (reel_id,)).fetchone()
        assert reel['active_job'] == job['id'] and reel['status'] == 'queued'
    assert backfill_titles(path) == 0  # Already queued; safe to run on every worker start.


def test_delivery_logs_status_and_counts_without_private_fields(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO, logger='uvicorn.error')
    with TestClient(create_app(tmp_path/'db', config=CFG)) as client:
        assert post(client, fixture()).status_code == 200
        assert client.post('/webhooks/instagram', content=b'private message', headers={'X-Hub-Signature-256':'sha256='+'0'*64}).status_code == 403
    assert 'Instagram webhook POST status=200' in caplog.text
    assert 'Instagram webhook POST status=403' in caplog.text
    assert 'messaging=1' in caplog.text
    for private in ('dummy-secret','dummy-verify','dummy-access-token','private message','cdn.example','Authored fixture'):
        assert private not in caplog.text
