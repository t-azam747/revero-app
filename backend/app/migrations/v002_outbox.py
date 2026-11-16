"""Remove the old inline UNIQUE(inbound_id) without losing delivery history."""

def upgrade(db):
    db.execute('''CREATE TABLE instagram_outbox_next (
        id INTEGER PRIMARY KEY, inbound_id INTEGER NOT NULL REFERENCES instagram_inbound(id),
        kind TEXT NOT NULL DEFAULT 'saved', text TEXT,
        state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
        available_at REAL NOT NULL DEFAULT 0, lease_until REAL, attempt_id TEXT,
        provider_mid TEXT, error TEXT, UNIQUE(inbound_id,kind))''')
    columns = 'id,inbound_id,kind,text,state,attempts,available_at,lease_until,attempt_id,provider_mid,error'
    db.execute(f'INSERT INTO instagram_outbox_next({columns}) SELECT {columns} FROM instagram_outbox')
    db.execute('DROP TABLE instagram_outbox')
    db.execute('ALTER TABLE instagram_outbox_next RENAME TO instagram_outbox')
    db.execute('CREATE UNIQUE INDEX idx_instagram_outbox_inbound_kind ON instagram_outbox(inbound_id,kind)')
