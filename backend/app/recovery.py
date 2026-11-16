"""Explicit owner actions after isolated restoration; never sends a provider request."""
import argparse
from pathlib import Path
import time
from .storage import connect


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('database',type=Path)
    parser.add_argument('--resume',choices=['processing','delivery'],required=True)
    parser.add_argument('--confirm-isolated-review',action='store_true',required=True)
    args=parser.parse_args()
    column='delivery_paused' if args.resume=='delivery' else 'processing_paused'
    with connect(args.database) as db:
        db.execute('BEGIN IMMEDIATE')
        if args.resume=='delivery':
            # Explicit resume does NOT replay old pending intents, even within today's window.
            for runs,parts in [('digest_runs','digest_messages'),('digest_manual_runs','digest_manual_messages')]:
                db.execute(f"UPDATE {runs} SET state='uncertain',attempt=NULL,error='Restored unsent run; inspect before retrying.' WHERE state IN ('pending','failed')")
                db.execute(f"UPDATE {parts} SET state='uncertain' WHERE state IN ('pending','failed')")
            db.execute("UPDATE instagram_outbox SET state='expired',error='restore_suppressed' WHERE state IN ('queued','failed')")
        db.execute(f'UPDATE runtime_controls SET {column}=0 WHERE id=1')
        db.execute('INSERT INTO operation_events(kind,created_at,outcome) VALUES(?,?,?)',('recovery',time.time(),args.resume+'_resumed'))
    print('Recovery control updated. Scheduling remains disabled until explicitly enabled in the workspace.')

if __name__=='__main__': main()
