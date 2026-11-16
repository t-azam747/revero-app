"""Frozen baseline schema; never edit after recording its checksum."""

def upgrade(db):
    db.execute('''CREATE TABLE IF NOT EXISTS reels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shortcode TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'needs_content',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )''')

    if 'active_job' not in {row['name'] for row in db.execute('PRAGMA table_info(reels)')}:
        db.execute('ALTER TABLE reels ADD COLUMN active_job INTEGER')
    db.execute('CREATE TABLE IF NOT EXISTS worker_state (name TEXT PRIMARY KEY, value REAL NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS extraction_jobs (
        id INTEGER PRIMARY KEY, reel_id INTEGER NOT NULL REFERENCES reels(id),
        revision TEXT NOT NULL, caption TEXT NOT NULL, media BLOB, mime TEXT,
        state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
        available_at REAL NOT NULL DEFAULT 0, lease_until REAL, priority INTEGER NOT NULL DEFAULT 0,
        error TEXT, result TEXT, created_at REAL NOT NULL,
        UNIQUE(reel_id, revision))''')
    if 'priority' not in {row['name'] for row in db.execute('PRAGMA table_info(extraction_jobs)')}:
        db.execute('ALTER TABLE extraction_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0')
    # Persistent token bucket and daily cap, so restarts cannot reset the free-tier budget.
    db.execute('''CREATE TABLE IF NOT EXISTS extraction_rate (
        id INTEGER PRIMARY KEY CHECK (id=1), tokens REAL NOT NULL,
        updated_at REAL NOT NULL, day_key TEXT NOT NULL, day_count INTEGER NOT NULL)''')

    db.execute('''CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY,
        reel_id INTEGER NOT NULL REFERENCES reels(id),
        job_id INTEGER NOT NULL REFERENCES extraction_jobs(id),
        suggestion_index INTEGER NOT NULL,
        text TEXT NOT NULL, source_excerpt TEXT NOT NULL,
        source_origin TEXT NOT NULL, timestamp_seconds REAL,
        date_mentions TEXT NOT NULL,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'done', 'dismissed')),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE(job_id, suggestion_index))''')

    db.execute('''CREATE TABLE IF NOT EXISTS digest_preferences (
        id INTEGER PRIMARY KEY CHECK(id=1), interests TEXT NOT NULL DEFAULT '[]', enabled INTEGER NOT NULL DEFAULT 0)''')
    db.execute('INSERT OR IGNORE INTO digest_preferences(id) VALUES (1)')
    if 'delivery_time' not in {row['name'] for row in db.execute('PRAGMA table_info(digest_preferences)')}:
        db.execute("ALTER TABLE digest_preferences ADD COLUMN delivery_time TEXT NOT NULL DEFAULT '23:00'")
    db.execute('''CREATE TABLE IF NOT EXISTS digest_runs (
        local_date TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL,
        started_at REAL, next_attempt_at REAL NOT NULL DEFAULT 0, error TEXT,
        sent_at REAL, attempt TEXT)''')
    if 'attempt' not in {row['name'] for row in db.execute('PRAGMA table_info(digest_runs)')}:
        db.execute('ALTER TABLE digest_runs ADD COLUMN attempt TEXT')
    db.execute('''CREATE TABLE IF NOT EXISTS digest_messages (
        local_date TEXT NOT NULL REFERENCES digest_runs(local_date), position INTEGER NOT NULL,
        text TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', message_id INTEGER,
        PRIMARY KEY(local_date, position))''')

    # Separate manual records reuse the same durable multipart delivery engine.
    db.execute("""CREATE TABLE IF NOT EXISTS digest_manual_runs (
        local_date TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL,
        started_at REAL, next_attempt_at REAL NOT NULL DEFAULT 0, error TEXT,
        sent_at REAL, attempt TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS digest_manual_messages (
        local_date TEXT NOT NULL REFERENCES digest_manual_runs(local_date), position INTEGER NOT NULL,
        text TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', message_id INTEGER,
        PRIMARY KEY(local_date, position))""")
    db.execute("""CREATE TABLE IF NOT EXISTS digest_manual_requests (
        request_id TEXT PRIMARY KEY, run_key TEXT NOT NULL REFERENCES digest_manual_runs(local_date))""")

    for statement in "\n        CREATE TABLE IF NOT EXISTS instagram_senders (\n            account_id TEXT NOT NULL, sender_id TEXT NOT NULL, first_seen REAL NOT NULL,\n            PRIMARY KEY(account_id, sender_id));\n        CREATE TABLE IF NOT EXISTS instagram_inbound (\n            id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, mid TEXT NOT NULL,\n            sender_id TEXT NOT NULL, event_at REAL NOT NULL, received_at REAL NOT NULL,\n            kind TEXT NOT NULL, UNIQUE(account_id, mid));\n        CREATE TABLE IF NOT EXISTS instagram_refs (\n            account_id TEXT NOT NULL, identity TEXT NOT NULL, reel_id INTEGER NOT NULL REFERENCES reels(id),\n            PRIMARY KEY(account_id, identity));\n        CREATE TABLE IF NOT EXISTS instagram_shares (\n            inbound_id INTEGER NOT NULL REFERENCES instagram_inbound(id), position INTEGER NOT NULL,\n            reel_id INTEGER NOT NULL REFERENCES reels(id), attachment_type TEXT NOT NULL,\n            provider_id TEXT, reference TEXT, title TEXT,\n            access_class TEXT NOT NULL DEFAULT 'unmeasured',\n            PRIMARY KEY(inbound_id, position));\n        CREATE TABLE IF NOT EXISTS instagram_outbox (\n            id INTEGER PRIMARY KEY, inbound_id INTEGER NOT NULL REFERENCES instagram_inbound(id),\n            kind TEXT NOT NULL DEFAULT 'saved', text TEXT,\n            state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,\n            available_at REAL NOT NULL DEFAULT 0, lease_until REAL, attempt_id TEXT,\n            provider_mid TEXT, error TEXT,\n            UNIQUE(inbound_id, kind));\n        ".split(";"):
        if statement.strip():
            db.execute(statement)
    columns = {row['name'] for row in db.execute('PRAGMA table_info(instagram_outbox)')}
    if 'kind' not in columns:
        db.execute("ALTER TABLE instagram_outbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'saved'")
    if 'text' not in columns:
        db.execute("ALTER TABLE instagram_outbox ADD COLUMN text TEXT")
