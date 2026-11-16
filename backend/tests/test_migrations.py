from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import create_app, initialize_database
from app.storage import connect,migrate,expected,initialize
from app import storage


def seed(path):
    initialize_database(path)
    with connect(path) as db:
        db.execute("INSERT INTO reels(id,shortcode,url,status) VALUES(1,'Sample','https://instagram.com/reel/Sample/','ready')")
        result={'summary':'Known source','topics':[],'suggestions':[],'date_candidates':[],
                'sources':[{'excerpt':'Known source','origin':'caption','timestamp_seconds':None}],
                'walkthrough':[{'step_number':1,'instruction':'Chromatic zebra correction','source_index':0}]}
        db.execute("INSERT INTO extraction_jobs(id,reel_id,revision,caption,state,result,created_at) VALUES(1,1,'revision','Known source','ready',?,1)",(json.dumps(result),))
        db.execute('UPDATE reels SET active_job=1 WHERE id=1')
        db.execute("INSERT INTO actions(id,reel_id,job_id,suggestion_index,text,source_excerpt,source_origin,date_mentions,status,due_date) VALUES(1,1,1,0,'Practice','Known source','caption','[]','open','2027-02-01')")
        for n,state in enumerate(('sent','uncertain','failed'),1):
            db.execute('INSERT INTO instagram_inbound(id,account_id,mid,sender_id,event_at,received_at,kind) VALUES(?,?,?,?,1,1,?)',(n,'100',str(n),'200','reel'))
            db.execute('INSERT INTO instagram_outbox(id,inbound_id,state,provider_mid) VALUES(?,?,?,?)',(n,n,state,'confirmed' if state=='sent' else None))
        db.execute("INSERT INTO digest_runs(local_date,state,payload,sent_at) VALUES('2026-11-16','sent','{}',1)")
        db.execute("INSERT INTO digest_messages VALUES('2026-11-16',0,'Frozen content','sent',123)")
        db.execute("INSERT INTO digest_manual_runs(local_date,state,payload) VALUES('manual','uncertain','{}')")
    return path


def legacy(path):
    seed(path)
    with connect(path) as db:
        db.execute('DROP TABLE schema_migrations')
        for table in ('runtime_controls','worker_heartbeats','operation_events'): db.execute('DROP TABLE '+table)
        db.execute('DROP INDEX idx_instagram_outbox_inbound_kind')
        db.execute('ALTER TABLE instagram_outbox RENAME TO original_outbox')
        db.execute('''CREATE TABLE instagram_outbox(id INTEGER PRIMARY KEY,inbound_id INTEGER NOT NULL UNIQUE,
            state TEXT DEFAULT 'queued',attempts INTEGER DEFAULT 0,available_at REAL DEFAULT 0,
            lease_until REAL,attempt_id TEXT,provider_mid TEXT,error TEXT)''')
        columns='id,inbound_id,state,attempts,available_at,lease_until,attempt_id,provider_mid,error'
        db.execute(f'INSERT INTO instagram_outbox({columns}) SELECT {columns} FROM original_outbox')
        db.execute('DROP TABLE original_outbox')
        for name in ('reel_search_active','reel_search_result','reel_search_delete'): db.execute('DROP TRIGGER '+name)
        db.execute('DROP VIEW reel_documents')
        db.execute('CREATE VIEW reel_documents AS SELECT r.id reel_id,j.id job_id,j.caption document FROM reels r JOIN extraction_jobs j ON j.id=r.active_job')
    return path


def test_legacy_upgrade_preserves_history_and_rebuilds_search(tmp_path):
    path=legacy(tmp_path/'db'); migrate(path)
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==4
        assert [(r['id'],r['state'],r['provider_mid']) for r in db.execute('SELECT * FROM instagram_outbox ORDER BY id')]==[(1,'sent','confirmed'),(2,'uncertain',None),(3,'failed',None)]
        db.execute("INSERT INTO instagram_outbox(inbound_id,kind,text) VALUES(1,'summary','Summary')")
        assert db.execute('SELECT message_id,text FROM digest_messages').fetchone()[:]==(123,'Frozen content')
        assert db.execute('SELECT state FROM digest_manual_runs').fetchone()[0]=='uncertain'
        assert db.execute('SELECT due_date FROM actions').fetchone()[0]=='2027-02-01'
        assert db.execute("SELECT count(*) FROM reel_search WHERE reel_search MATCH 'chromatic'").fetchone()[0]==1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    snapshots=list((path.parent/'pre-upgrade').glob('*.sqlite3'))
    assert len(snapshots)==1
    with sqlite3.connect(snapshots[0]) as db: assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    migrate(path)
    assert len(list((path.parent/'pre-upgrade').glob('*.sqlite3')))==1


def test_failure_rolls_back_all_pending_and_can_recover(tmp_path,monkeypatch):
    path=legacy(tmp_path/'db'); original=storage.expected
    plan=original()
    def fail(db):
        db.execute('CREATE TABLE should_rollback(id INTEGER)')
        raise RuntimeError('injected migration failure')
    monkeypatch.setattr(storage,'expected',lambda:[plan[0],(2,plan[1][1],fail),*plan[2:]])
    with pytest.raises(RuntimeError,match='injected'): migrate(path)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('schema_migrations','should_rollback')").fetchall()
        assert db.execute('SELECT count(*) FROM instagram_outbox').fetchone()[0]==3
    monkeypatch.setattr(storage,'expected',original); migrate(path)


def test_checksum_fail_closed_and_runtime_requires_explicit_upgrade(tmp_path,monkeypatch):
    path=tmp_path/'db'; migrate(path)
    with connect(path) as db: db.execute("UPDATE schema_migrations SET checksum='changed' WHERE version=1")
    with pytest.raises(RuntimeError,match='history differs'): migrate(path)
    other=tmp_path/'new'
    monkeypatch.setenv('REVERO_REQUIRE_MIGRATED','true')
    with pytest.raises(RuntimeError,match='explicit migration'): initialize(other)
    migrate(other); initialize(other)


def test_concurrent_initializers_and_app_writes_share_constraints(tmp_path):
    path=tmp_path/'db'
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(lambda _:migrate(path),range(4)))
    with TestClient(create_app(path)) as client:
        def save(_): return client.post('/api/reels',json={'url':'https://instagram.com/reel/Concurrent/'}).json()
        with ThreadPoolExecutor(max_workers=6) as pool: rows=list(pool.map(save,range(18)))
        assert sum(r['created'] for r in rows)==1
    with connect(path) as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        assert db.execute('PRAGMA foreign_keys').fetchone()[0]==1
        assert db.execute('PRAGMA busy_timeout').fetchone()[0]==15000
        with pytest.raises(sqlite3.IntegrityError): db.execute("INSERT INTO instagram_outbox(inbound_id) VALUES(9999)")
