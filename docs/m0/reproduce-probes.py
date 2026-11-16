"""M0 audit only: reproduce upgrade/connection observations in temporary databases.
Run from root: PYTHONPATH=backend backend/.venv/bin/python docs/m0/reproduce-probes.py
No providers, personal inbox, migrations of personal data, or deliveries are used.
"""
from pathlib import Path
import sqlite3
import tempfile
from app.main import initialize_database
from app import extraction, instagram, search

with tempfile.TemporaryDirectory(prefix='revero-m0-probe-') as directory:
    path = Path(directory)/'fresh.db'
    initialize_database(path)
    with extraction.connect(path) as db:
        print('helper FK/timeout/journal:', *(db.execute('PRAGMA '+name).fetchone()[0] for name in ('foreign_keys','busy_timeout','journal_mode')))
        db.execute('DROP VIEW reel_documents')
        db.execute('CREATE VIEW reel_documents AS SELECT r.id AS reel_id,j.id AS job_id,j.caption AS document FROM reels r JOIN extraction_jobs j ON r.active_job=j.id')
        search.initialize(db)
        print('old view remains stale:', 'walkthrough' not in db.execute("SELECT sql FROM sqlite_master WHERE name='reel_documents'").fetchone()[0])
    with sqlite3.connect(path, timeout=10) as db:
        print('main-equivalent FK/timeout:', *(db.execute('PRAGMA '+name).fetchone()[0] for name in ('foreign_keys','busy_timeout')))
    old = Path(directory)/'legacy.db'
    with sqlite3.connect(old) as db:
        db.execute("CREATE TABLE instagram_outbox(id INTEGER PRIMARY KEY,inbound_id INTEGER NOT NULL UNIQUE,state TEXT DEFAULT 'queued',attempts INTEGER DEFAULT 0,available_at REAL DEFAULT 0,lease_until REAL,attempt_id TEXT,provider_mid TEXT,error TEXT)")
    instagram.initialize(old)
    with sqlite3.connect(old) as db:
        db.execute("INSERT INTO instagram_outbox(inbound_id,kind) VALUES(1,'saved')")
        try:
            db.execute("INSERT INTO instagram_outbox(inbound_id,kind) VALUES(1,'summary')")
        except sqlite3.IntegrityError:
            print('legacy outbox rejects summary after saved: True')
