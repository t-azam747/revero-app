"""Hourly encrypted snapshots to an operator-supplied independent storage mount."""
import logging
import os
from pathlib import Path
import time
from .backups import backup, retention_candidates
from .operations import worker_guard
from .remote_backup import client_and_target, upload_verified, prune
from .main import DEFAULT_DB
from .storage import initialize


def main():
    initialize(DEFAULT_DB)
    target=Path(os.environ['REVERO_BACKUP_TARGET'])
    key=Path(os.environ['REVERO_BACKUP_KEY_FILE'])
    with worker_guard(DEFAULT_DB,'backup'):
        while True:
            try:
                artifact = backup(DEFAULT_DB,target,key)
                client,bucket,prefix = client_and_target()
                upload_verified(DEFAULT_DB,artifact,client,bucket,prefix)
                if os.environ.get('REVERO_BACKUP_PRUNE_CONFIRMED')=='true':
                    prune(client,bucket,prefix)
                    for pair in retention_candidates(target):
                        for file in pair: file.unlink()
            except Exception:
                logging.warning('Encrypted backup failed; last-success age remains unchanged.')
            time.sleep(1800)  # 30-minute cadence leaves margin for the one-hour RPO objective.

if __name__=='__main__': main()
