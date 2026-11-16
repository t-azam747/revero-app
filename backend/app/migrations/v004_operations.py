"""Operational guards and observable process ownership."""

def upgrade(db):
    db.execute('''CREATE TABLE runtime_controls (
        id INTEGER PRIMARY KEY CHECK(id=1), delivery_paused INTEGER NOT NULL DEFAULT 0,
        processing_paused INTEGER NOT NULL DEFAULT 0, restored_at REAL)''')
    db.execute('INSERT INTO runtime_controls(id) VALUES(1)')
    db.execute('''CREATE TABLE worker_heartbeats (
        name TEXT PRIMARY KEY, owner TEXT NOT NULL, updated_at REAL NOT NULL)''')
    db.execute('''CREATE TABLE operation_events (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, created_at REAL NOT NULL,
        outcome TEXT NOT NULL)''')
