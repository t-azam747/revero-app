"""Transactional canonical save primitive shared by intake adapters."""


def save(db, shortcode, url):
    cursor = db.execute(
        'INSERT INTO reels (shortcode, url) VALUES (?, ?) ON CONFLICT(shortcode) DO NOTHING',
        (shortcode, url),
    )
    row = db.execute('SELECT * FROM reels WHERE shortcode=?', (shortcode,)).fetchone()
    return row, cursor.rowcount == 1
