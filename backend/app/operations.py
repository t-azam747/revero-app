"""Local-disk process ownership, safe operational signals and restore guards."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import threading
import time
import uuid

from .storage import connect, validate


def paused_db(db, kind):
    column = 'delivery_paused' if kind == 'delivery' else 'processing_paused'
    return bool(db.execute(f'SELECT {column} FROM runtime_controls WHERE id=1').fetchone()[0])


def paused(path, kind):
    with connect(path) as db:
        return paused_db(db,kind)


@contextmanager
def worker_guard(path,name):
    """Kernel lock spans containers sharing the same local-disk volume, released on death."""
    directory=Path(path).parent/'.locks'; directory.mkdir(exist_ok=True)
    with (directory/(name+'.lock')).open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('This worker role already has an active owner.') from None
        owner=uuid.uuid4().hex; stop=threading.Event()
        def pulse():
            while not stop.is_set():
                try:
                    with connect(path) as db:
                        db.execute('INSERT INTO worker_heartbeats VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,updated_at=excluded.updated_at',(name,owner,time.time()))
                except Exception:
                    pass  # Health becomes stale; never emit SQL, payloads or credentials.
                stop.wait(5)
        thread=threading.Thread(target=pulse,daemon=True); thread.start()
        try: yield
        finally: stop.set(); thread.join(timeout=20)


def status(path, now=None):
    now=time.time() if now is None else now
    with connect(path) as db:
        count,plan=validate(db)
        controls=dict(db.execute('SELECT * FROM runtime_controls WHERE id=1').fetchone())
        hearts=[{'role':r['name'],'age_seconds':max(0,now-r['updated_at']),'healthy':now-r['updated_at']<45} for r in db.execute('SELECT * FROM worker_heartbeats')]
        queues={}
        for table in ('extraction_jobs','instagram_outbox','digest_runs','digest_manual_runs'):
            queues[table]={r[0]:r[1] for r in db.execute(f'SELECT state,count(*) FROM {table} GROUP BY state')}
        oldest=db.execute("SELECT min(created_at) FROM extraction_jobs WHERE state IN ('queued','processing')").fetchone()[0]
        last=db.execute("SELECT max(created_at) FROM operation_events WHERE kind='backup' AND outcome='verified'").fetchone()[0]
    return {'schema_current':count==len(plan),'controls':controls,'workers':hearts,'queues':queues,
            'oldest_processing_work_age_seconds':None if oldest is None else max(0,now-oldest),
            'backup_age_seconds':None if last is None else max(0,now-last),
            'database_bytes':Path(path).stat().st_size}


def main():
    import argparse
    from .main import DEFAULT_DB
    parser=argparse.ArgumentParser(); parser.add_argument('--role'); parser.add_argument('--database',type=Path,default=DEFAULT_DB)
    args=parser.parse_args(); value=status(args.database)
    if args.role:
        healthy=any(r['role']==args.role and r['healthy'] for r in value['workers'])
        print('healthy' if healthy else 'stale_or_missing'); raise SystemExit(0 if healthy else 1)
    print(json.dumps(value,indent=2))

if __name__=='__main__': main()
