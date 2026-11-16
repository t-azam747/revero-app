"""Rebuild the versioned search view and its derived index."""
DOCUMENTS = """SELECT r.id AS reel_id, j.id AS job_id,
    j.caption || ' ' || coalesce(json_extract(j.result, '$.summary'), '') || ' ' ||
    coalesce((SELECT group_concat(value, ' ') FROM json_each(j.result, '$.topics')), '') || ' ' ||
    coalesce((SELECT group_concat(json_extract(value, '$.text'), ' ') FROM json_each(j.result, '$.suggestions')), '') || ' ' ||
    coalesce((SELECT group_concat(json_extract(value, '$.excerpt'), ' ') FROM json_each(j.result, '$.sources')), '') || ' ' ||
    coalesce((SELECT group_concat(json_extract(value, '$.instruction') || ' ' || coalesce(json_extract(value, '$.spoken_text'), '') || ' ' || coalesce(json_extract(value, '$.on_screen_text'), ''), ' ') FROM json_each(j.result, '$.walkthrough')), '') AS document
    FROM reels r JOIN extraction_jobs j ON j.id=r.active_job"""

def upgrade(db):
    for name in ('reel_search_active','reel_search_result','reel_search_delete'):
        db.execute('DROP TRIGGER IF EXISTS ' + name)
    db.execute('DROP VIEW IF EXISTS reel_documents')
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS reel_search USING fts5(reel_id UNINDEXED, job_id UNINDEXED, document, tokenize='porter unicode61')")
    db.execute('CREATE VIEW reel_documents AS ' + DOCUMENTS)
    for name, event, key in [('reel_search_active', 'UPDATE OF active_job, status ON reels', 'NEW.id'),
                              ('reel_search_result', 'UPDATE OF result, caption ON extraction_jobs', 'NEW.reel_id')]:
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS {name} AFTER {event} BEGIN
            DELETE FROM reel_search WHERE reel_id={key};
            INSERT INTO reel_search(reel_id, job_id, document) SELECT reel_id, job_id, document FROM reel_documents WHERE reel_id={key};
            END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS reel_search_delete AFTER DELETE ON reels BEGIN
                   DELETE FROM reel_search WHERE reel_id=OLD.id; END''')
    # Backfill existing saves on upgrade; subsequent changes are updated transactionally by triggers.
    db.execute('DELETE FROM reel_search')
    db.execute('INSERT INTO reel_search(reel_id, job_id, document) SELECT * FROM reel_documents')
