"""Encrypted SQLite snapshots and fail-closed isolated restore. No provider clients."""
import argparse
from datetime import datetime,timezone
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from cryptography.fernet import Fernet
from .storage import snapshot, migrate, connect

MAX_SNAPSHOT = 256 * 1024 * 1024


def exclusive(path,content):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as file:
        file.write(content); file.flush(); os.fsync(file.fileno())


def generate_key(path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    exclusive(path,Fernet.generate_key())


def cipher(key_file):
    key_file=Path(key_file)
    if key_file.stat().st_mode & 0o077:
        raise ValueError('Backup key must be readable only by its owner.')
    return Fernet(key_file.read_bytes().strip())


def check_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Snapshot validation failed.')


def backup(database,target,key_file):
    database,target,key_file=Path(database).resolve(),Path(target).resolve(),Path(key_file).resolve()
    if key_file.is_relative_to(database.parent) or key_file.is_relative_to(target):
        raise ValueError('Keep the recovery key outside database and backup directories.')
    crypt=cipher(key_file); target.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='revero-backup-') as temporary:
        plain=snapshot(database,Path(temporary)/'snapshot.sqlite3')
        if plain.stat().st_size>MAX_SNAPSHOT: raise ValueError('Snapshot exceeds the bounded backup size; inspect storage before retrying.')
        check_database(plain)
        raw=plain.read_bytes(); encrypted=crypt.encrypt(raw)
        # Verify authentication and exact snapshot content before declaring success.
        if crypt.decrypt(encrypted)!=raw: raise ValueError('Encrypted snapshot verification failed.')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        name='revero-'+stamp+'-'+uuid.uuid4().hex
        artifact=target/(name+'.rvbk')
        exclusive(artifact,encrypted)
        if hashlib.sha256(artifact.read_bytes()).digest()!=hashlib.sha256(encrypted).digest():
            raise ValueError('Stored backup verification failed.')
        manifest={'format':'fernet-sqlite-v1','created_at':time.time(),'ciphertext_sha256':hashlib.sha256(encrypted).hexdigest(),'snapshot_bytes':len(raw)}
        exclusive(target/(name+'.json'),json.dumps(manifest,indent=2).encode())
    with connect(database) as db:
        db.execute("INSERT INTO operation_events(kind,created_at,outcome) VALUES('backup_local',?,'verified')",(time.time(),))
    return artifact


def restore(artifact,destination,key_file):
    artifact,destination=Path(artifact).resolve(),Path(destination).resolve()
    if destination.exists() or Path(str(destination)+'-wal').exists() or Path(str(destination)+'-shm').exists():
        raise ValueError('Restore requires a new isolated destination.')
    if artifact.stat().st_size>MAX_SNAPSHOT*2: raise ValueError('Backup exceeds the restore size limit.')
    # Authentication completes before any SQLite access or promotion.
    raw=cipher(key_file).decrypt(artifact.read_bytes())
    if len(raw)>MAX_SNAPSHOT: raise ValueError('Snapshot exceeds the restore size limit.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.revero-restore-',dir=destination.parent) as tmp:
        stage=Path(tmp)/'restored.sqlite3'; exclusive(stage,raw)
        check_database(stage); migrate(stage)
        with connect(stage) as db:
            db.execute('UPDATE runtime_controls SET delivery_paused=1,processing_paused=1,restored_at=? WHERE id=1',(time.time(),))
            db.execute('UPDATE digest_preferences SET enabled=0')
            for runs,parts in [('digest_runs','digest_messages'),('digest_manual_runs','digest_manual_messages')]:
                db.execute(f"UPDATE {runs} SET state='uncertain',attempt=NULL,error='Restored during delivery; review before retrying.' WHERE state='sending'")
                db.execute(f"UPDATE {parts} SET state='uncertain' WHERE state='sending'")
            db.execute("UPDATE instagram_outbox SET state='uncertain',attempt_id=NULL,error='restored_during_send' WHERE state='sending'")
            db.execute('DELETE FROM worker_heartbeats')
            db.execute("INSERT INTO operation_events(kind,created_at,outcome) VALUES('restore',?,'paused')",(time.time(),))
        check_database(stage)
        # Use SQLite backup to a newly created destination; no live DB is ever overwritten.
        snapshot(stage,destination)
    return destination


def retention_candidates(target,now=None):
    """Explicit retention: hourly 48h, daily 30d, weekly 12w. Only complete paired artifacts."""
    now=time.time() if now is None else now
    kept=set(); delete=[]
    manifests=sorted(Path(target).glob('revero-*.json'),reverse=True)
    for manifest in manifests:
        artifact=manifest.with_suffix('.rvbk')
        if not artifact.exists(): continue
        value=json.loads(manifest.read_text()); stamp=float(value['created_at']); age=now-stamp
        date=datetime.fromtimestamp(stamp,timezone.utc)
        if age<0: continue
        if age<48*3600: bucket=('hour',date.strftime('%Y%m%d%H'))
        elif age<30*86400: bucket=('day',date.strftime('%Y%m%d'))
        elif age<12*7*86400: bucket=('week',date.strftime('%G%V'))
        else: bucket=None
        if bucket is None or bucket in kept: delete.append((artifact,manifest))
        else: kept.add(bucket)
    return delete


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest='command',required=True)
    key=sub.add_parser('keygen'); key.add_argument('key_file',type=Path)
    for name in ('backup','restore'):
        cmd=sub.add_parser(name); cmd.add_argument('source',type=Path); cmd.add_argument('destination',type=Path); cmd.add_argument('--key-file',type=Path,required=True)
    prune=sub.add_parser('prune'); prune.add_argument('target',type=Path); prune.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='keygen': generate_key(args.key_file)
        elif args.command=='backup': backup(args.source,args.destination,args.key_file)
        elif args.command=='restore': restore(args.source,args.destination,args.key_file)
        else:
            candidates=retention_candidates(args.target); print('retention_candidates:',len(candidates))
            if args.apply:
                for pair in candidates:
                    for file in pair: file.unlink()
        print('Operation completed.')
    except Exception:
        # CLI exit status is preserved; no exception can print filenames/keys/provider data.
        print('Operation failed. Check protected configuration, destination, integrity and permissions.'); raise SystemExit(1)

if __name__=='__main__': main()
