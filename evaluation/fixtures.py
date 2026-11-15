"""Public-safe authored content and providers for isolated evaluation/demo only."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.extraction import ProviderError, connect, run_one

FIXTURES = Path(__file__).parent / 'fixtures'
DEMO_CAPTION = 'For backend interviews, practice SQLite joins. Review one query plan each week.'
# Synthetic evaluation isolates extraction plumbing from live free-tier limits.
UNLIMITED = {'rpm': 1000, 'rpd': 100000, 'batch': 5, 'max_attempts': 4}


def dataset():
    return json.loads((FIXTURES / 'synthetic.json').read_text())


def takeaway(case):
    origin = 'video' if case.get('kind') == 'video' else 'caption'
    return {'summary': case['caption'], 'topics': case.get('topics', ['Practice']),
            'suggestions': [] if case['key'] == 'blue-clip' else [{'text': case['caption'], 'source_index': 0}],
            'date_candidates': [{'original_text': text, 'source_index': 0} for text in case['date_mentions']],
            'sources': [{'excerpt': case['caption'], 'origin': origin,
                         'timestamp_seconds': case.get('timestamp_seconds') if origin == 'video' else None}]}


class FixtureProvider:
    def __init__(self, cases=None):
        self.cases = {case['caption']: case for case in (cases or dataset()['cases']) if case['caption']}
        self.calls = 0
        self.failed = set()

    def extract(self, caption, video_path, mime):
        self.calls += 1
        case = self.cases.get(caption)
        if case is None and caption == DEMO_CAPTION:
            case = {'key': 'live-demo-save', 'caption': caption, 'date_mentions': [], 'topics': ['backend interviews', 'SQLite']}
        if case is None:
            raise ProviderError('Offline fixture provider only accepts the authored demo captions.')
        if case.get('fail_once') and case['key'] not in self.failed:
            self.failed.add(case['key'])
            raise ProviderError('Simulated unreadable extraction. Retry is available.')
        return takeaway(case)


class FixtureAnswerer:
    def answer(self, question, sources):
        # Exact excerpts keep the stand-in grounded; this is not an AI quality measurement.
        return {'claims': [{'text': source['excerpt'], 'source_ids': [source['id']]} for source in sources[:2]]}


class FixtureMessenger:
    def __init__(self): self.sent = []
    def send(self, text):
        self.sent.append(text)
        return len(self.sent)


def seed(client, path, *, provider=None, retry=False):
    data = dataset()
    provider = provider or FixtureProvider(data['cases'])
    mapping = {}
    for case in data['cases']:
        response = client.post('/api/reels', json={'url': case['url']})
        response.raise_for_status()
        row = response.json()
        mapping[case['key']] = row['id']
        with connect(path) as db:
            db.execute('UPDATE reels SET created_at=? WHERE id=?', (case['created_at'], row['id']))
        if not case['caption']:
            continue
        files = None
        if case.get('kind') == 'video':
            clip = (FIXTURES / case['clip']).resolve()
            if not clip.is_file():
                raise RuntimeError(f'Missing authored video fixture: {clip.name}')
            files = {'video': (clip.name, clip.read_bytes(), 'video/mp4')}
        result = client.post(f"/api/reels/{row['id']}/content", data={'caption': case['caption']}, files=files)
        result.raise_for_status()
        run_one(path, provider, limits=UNLIMITED)
        if retry and case.get('fail_once'):
            client.post(f"/api/reels/{row['id']}/retry").raise_for_status()
            run_one(path, provider, limits=UNLIMITED)
    client.put('/api/digest/preferences', json={'interests': data['interests'], 'enabled': False}).raise_for_status()
    return mapping, provider
