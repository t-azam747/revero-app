"""Consistent SQLite access, serialized upgrades and pre-upgrade snapshots."""
from contextlib import contextmanager, closing
import hashlib
from importlib import import_module
import os
from pathlib import Path
import sqlite3
import time
import uuid

VERSIONS = ('v001_baseline','v002_outbox','v003_search','v004_operations')


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        # Persistent database setting; no external work in this connection scope.
        if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
            db.execute('PRAGMA journal_mode=WAL')
        with db:
            yield db
    finally:
        db.close()


def expected():
    result=[]
    for version,name in enumerate(VERSIONS,1):
        module=import_module('.migrations.'+name, __package__)
        result.append((version,hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),module.upgrade))
    return result


def validate(db):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    rows=db.execute('SELECT version,checksum FROM schema_migrations ORDER BY version').fetchall() if exists else []
    plan=expected()
    if len(rows)>len(plan) or any(row[0]!=plan[i][0] or row[1]!=plan[i][1] for i,row in enumerate(rows)):
        raise RuntimeError('Migration history differs from this application; stop and restore the matching release.')
    return len(rows),plan


def snapshot(source,destination):
    """Online backup includes committed WAL content; never copy just the main DB file."""
    source,destination=Path(source).resolve(),Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=15)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst,pages=256,sleep=.01)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def initialize(path):
    path=Path(path).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
    # In production, migrate once before supervision starts. Runtime processes fail closed.
    if os.environ.get('REVERO_REQUIRE_MIGRATED')=='true':
        with connect(path) as db:
            count,plan=validate(db)
            if count!=len(plan): raise RuntimeError('Run the explicit migration command before starting services.')
        return
    migrate(path)


def migrate(path):
    path=Path(path).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
    existed=path.exists() and path.stat().st_size>0
    # Preflight read-only; snapshots are private local rollback aids, not encrypted off-host backups.
    if existed:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            count,plan=validate(db)
        if count==len(plan): return
        snapshot(path,path.parent/'pre-upgrade'/('snapshot-'+str(time.time_ns())+'-'+uuid.uuid4().hex+'.sqlite3'))
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        count,plan=validate(db)
        db.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)''')
        for version,checksum,upgrade in plan[count:]:
            upgrade(db)
            db.execute('INSERT INTO schema_migrations VALUES(?,?,?)',(version,checksum,time.time()))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign-key violations: upgrade rolled back; inspect the protected snapshot.')


def main():
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('database',type=Path); args=parser.parse_args()
    migrate(args.database)
    print('Schema verified and up to date.')

if __name__=='__main__': main()
