"""Local-only status and explicit uncertain-send resolution. No secrets or URLs printed."""
import argparse
import json
from .instagram import initialize
from .extraction import connect
from .main import DEFAULT_DB


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resolve', type=int, help='Outbox ID; inspect Instagram first.')
    parser.add_argument('--outcome', choices=['delivered', 'not-delivered'])
    args = parser.parse_args()
    initialize(DEFAULT_DB)
    with connect(DEFAULT_DB) as db:
        if args.resolve is not None:
            if not args.outcome:
                parser.error('--resolve needs --outcome')
            db.execute("UPDATE instagram_outbox SET state=?,error=NULL,available_at=0 WHERE id=? AND state='uncertain'",
                       ('sent' if args.outcome == 'delivered' else 'queued', args.resolve))
        report = {
            'sender_candidates_local_only': [dict(r) for r in db.execute('SELECT * FROM instagram_senders')],
            'inbound_counts': [dict(r) for r in db.execute('SELECT kind,count(*) AS count FROM instagram_inbound GROUP BY kind')],
            'shares': [dict(r) for r in db.execute('''SELECT s.inbound_id,s.reel_id,s.attachment_type,
                s.provider_id IS NOT NULL AS has_provider_id, s.reference IS NOT NULL AS has_reference,
                s.title IS NOT NULL AS has_title, r.url != '' AS has_canonical_permalink,s.access_class
                FROM instagram_shares s JOIN reels r ON r.id=s.reel_id''')],
            'outbox': [dict(r) for r in db.execute('SELECT id,state,attempts,error FROM instagram_outbox')],
            'playable_video': 'unmeasured; no URLs downloaded or inferred playable',
        }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
