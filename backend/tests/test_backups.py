from io import BytesIO
import json
from pathlib import Path
import sqlite3
import time

import pytest
from cryptography.fernet import InvalidToken
from app.backups import backup,restore,generate_key,retention_candidates
from app.storage import connect
from app.digest import run_digest,tick
from app.instagram import Config,run_one
from app.extraction import claim,rate_settings
from app.remote_backup import upload_verified
from test_migrations import seed


def test_encryption_restore_pauses_all_background_external_work(tmp_path):
    original=seed(tmp_path/'data'/'db'); key=tmp_path/'keys'/'key'; generate_key(key)
    with connect(original) as db:
        db.execute("UPDATE instagram_outbox SET state='sending',lease_until=1 WHERE id=3")
        db.execute('UPDATE digest_preferences SET enabled=1')
    artifact=backup(original,tmp_path/'backups',key)
    assert b'SQLite format' not in artifact.read_bytes()
    assert b'Known source' not in artifact.read_bytes()
    destination=tmp_path/'clean'/'db'
    restore(artifact,destination,key)
    with connect(destination) as db:
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert db.execute('SELECT provider_mid FROM instagram_outbox WHERE id=1').fetchone()[0]=='confirmed'
        assert db.execute('SELECT state FROM instagram_outbox WHERE id=3').fetchone()[0]=='uncertain'
        assert db.execute('SELECT message_id FROM digest_messages').fetchone()[0]==123
        assert db.execute('SELECT enabled FROM digest_preferences').fetchone()[0]==0
    class NoSend:
        def send(self,*args): pytest.fail('Restore must never call a messaging provider.')
    with pytest.raises(Exception,match='paused'): run_digest(destination,NoSend())
    assert tick(destination,NoSend()) is None
    assert not run_one(destination,Config(account_id='100',sender_id='200',replies_enabled=True),NoSend())
    assert not claim(destination,time.time(),rate_settings(),1)
    with pytest.raises(ValueError,match='new isolated'): restore(artifact,destination,key)


def test_tampered_or_wrong_key_backup_never_promotes(tmp_path):
    path=seed(tmp_path/'data'/'db'); key=tmp_path/'key'; generate_key(key)
    artifact=backup(path,tmp_path/'backups',key)
    other=tmp_path/'other'; generate_key(other)
    with pytest.raises(InvalidToken): restore(artifact,tmp_path/'target',other)
    assert not (tmp_path/'target').exists()
    encrypted=bytearray(artifact.read_bytes()); encrypted[-10]^=1; artifact.write_bytes(encrypted)
    with pytest.raises(InvalidToken): restore(artifact,tmp_path/'target',key)
    assert not (tmp_path/'target').exists()


def test_remote_verified_success_and_failure_do_not_fake_backup_age(tmp_path):
    path=seed(tmp_path/'data'/'db'); key=tmp_path/'key'; generate_key(key)
    artifact=backup(path,tmp_path/'backups',key)
    class Store:
        objects={}
        corrupt=False
        def put_object(self,**args): self.objects[args['Key']]=args['Body']
        def get_object(self,**args): return {'Body':BytesIO(b'corrupt' if self.corrupt else self.objects[args['Key']])}
    store=Store(); store.corrupt=True
    with pytest.raises(ValueError,match='verification'): upload_verified(path,artifact,store,'private-bucket','revero/')
    with connect(path) as db: assert db.execute("SELECT count(*) FROM operation_events WHERE kind='backup'").fetchone()[0]==0
    store.corrupt=False; upload_verified(path,artifact,store,'private-bucket','revero/')
    with connect(path) as db: assert db.execute("SELECT count(*) FROM operation_events WHERE kind='backup'").fetchone()[0]==1


def test_retention_only_deletes_eligible_paired_artifacts(tmp_path):
    now=time.time()
    for index,age in enumerate((10,20,86400*2+10,86400*2+20,86400*100)):
        stem=tmp_path/f'revero-{index:03}'
        stem.with_suffix('.rvbk').write_bytes(b'encrypted')
        stem.with_suffix('.json').write_text(json.dumps({'created_at':now-age}))
    pairs=retention_candidates(tmp_path,now)
    assert len(pairs)==3
    assert all(a.exists() and b.exists() for a,b in pairs)
