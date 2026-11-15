"""Run: backend/.venv/bin/python -m evaluation.benchmark. Never calls external providers."""
from datetime import datetime
import json
from pathlib import Path
import tempfile

from .fixtures import ROOT, UNLIMITED, FixtureAnswerer, FixtureMessenger, dataset, seed
from .metrics import ranking_metrics
from fastapi.testclient import TestClient
from app.main import create_app
from app.digest import build, messages, run_digest
from app.extraction import connect, run_one


def run_benchmark(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = dataset()
    sender = FixtureMessenger()
    with tempfile.TemporaryDirectory(prefix='revero-benchmark-') as directory:
        path = Path(directory) / 'evaluation.sqlite3'
        with TestClient(create_app(path, answerer=FixtureAnswerer(), messenger=sender)) as client:
            ids, provider = seed(client, path)
            initial = {row['shortcode']: row['status'] for row in client.get('/api/reels').json()}
            retry_id = ids['retry-case']
            failed_before_retry = client.get(f'/api/reels/{retry_id}/content').json()['job']['state'] == 'failed'
            client.post(f'/api/reels/{retry_id}/retry').raise_for_status()
            run_one(path, provider, limits=UNLIMITED)
            retry_ok = failed_before_retry and client.get(f'/api/reels/{retry_id}/content').json()['job']['state'] == 'ready'
            original = client.get('/api/reels').json()[0]
            duplicate = client.post('/api/reels', json={'url': original['url'] + '?igsh=benchmark'}).json()
            invalid_ok = client.post('/api/reels', json={'url': 'https://example.com/reel/not-instagram/'}).status_code == 400
            labels = {ids[case['key']]: case['relevance'] for case in data['cases']}
            names = {identifier: key for key, identifier in ids.items()}
            now = datetime.fromisoformat(data['as_of'])
            digest = build(path, now)
            with connect(path) as db:
                ready = db.execute("SELECT id FROM reels WHERE status='ready' ORDER BY created_at DESC, id DESC").fetchall()
            candidate_ids = [row['id'] for row in ready]
            # Preserve the same candidate pool for the ranked and newest-first metrics.
            from app.digest import rank_reels
            with connect(path) as db:
                rows = db.execute("SELECT r.*, j.result FROM reels r JOIN extraction_jobs j ON j.id=r.active_job WHERE r.status='ready' AND j.state='ready'").fetchall()
            ranked_ids = [row['id'] for row in rank_reels(rows, data['interests'])]
            wording_total = wording_correct = evidence_total = evidence_correct = 0
            unexpected_due_dates = sum(action['due_date'] is not None for action in client.get('/api/actions').json())
            for case in data['cases']:
                content = client.get(f"/api/reels/{ids[case['key']]}/content").json()['job']
                if not content or not content['takeaway']:
                    continue
                result = content['takeaway']
                for source in result['sources']:
                    evidence_total += 1
                    evidence_correct += source['excerpt'] == case['caption'] and source['origin'] == ('video' if case.get('kind') == 'video' else 'caption')
                expected = set(case['date_mentions'])
                actual = {item['original_text'] for item in result['date_candidates']}
                wording_total += len(expected)
                wording_correct += len(expected & actual)
                if case.get('confirm_date'):
                    action = client.post('/api/actions', json={'job_id': content['id'], 'suggestion_index': 0}).json()
                    assert action['due_date'] is None
                    client.patch(f"/api/actions/{action['id']}", json={'due_date': case['confirm_date']}).raise_for_status()
            digest = build(path, now)
            relevant = client.post('/api/ask', json={'question': 'What did I save about SQLite joins?'}).json()
            no_match = client.post('/api/ask', json={'question': 'quantum entanglement research'}).json()
            first = run_digest(path, sender, now)
            run_digest(path, sender, now)
            provided = sum(bool(case['caption']) for case in data['cases'])
            report = {
                'scope': 'Authored synthetic fixture benchmark; deterministic providers, no Gemini/Instagram/Telegram quality or accessibility measurement.',
                'as_of': data['as_of'], 'interests': data['interests'], 'sample_size': len(data['cases']),
                'real_reel_sample_size': 0, 'external_provider_calls': 0, 'inputs_supplied': provided,
                'initial_ready': sum(state == 'ready' for state in initial.values()),
                'ready_after_retry': len(candidate_ids), 'needs_content_after_retry': sum(row['status'] == 'needs_content' for row in client.get('/api/reels').json()),
                'input_processing_coverage_after_retry': len(candidate_ids) / provided,
                'total_inbox_ready_fraction': len(candidate_ids) / len(data['cases']),
                'retry_recovered': retry_ok,
                'duplicate_same_id': duplicate['id'] == original['id'] and duplicate['created'] is False,
                'invalid_link_rejected': invalid_ok,
                'reference_evidence_checks': {'passed': evidence_correct, 'total': evidence_total},
                'reference_date_wording_checks': {'passed': wording_correct, 'total': wording_total},
                'automatically_created_deadlines': unexpected_due_dates,
                'ranking': {'candidate_count': len(candidate_ids), 'ranked_top3': [names[item] for item in ranked_ids[:3]],
                            'newest_top3': [names[item] for item in candidate_ids[:3]],
                            'ranked': ranking_metrics(ranked_ids, labels), 'newest': ranking_metrics(candidate_ids, labels)},
                'retrieval_answered_from_fixture': relevant['status'] == 'answered',
                'unsupported_question_declined': no_match['status'] == 'no_match',
                'digest_state': first['state'], 'digest_parts_sent': len(sender.sent),
                'digest_rerun_no_duplicate': len(sender.sent) == len(messages(digest)),
                'limitations': ['Labels and content were authored together; sample is not representative.',
                                'Reference-provider checks measure plumbing, not model accuracy.',
                                'No week of usage, real-Reel accessibility, live model quality, or real Telegram delivery has been measured.']}
            (output / 'synthetic-report.json').write_text(json.dumps(report, indent=2) + '\n')
            (output / 'sample-digest.txt').write_text('OFFLINE SAMPLE — authored content; simulated delivery\n\n' + '\n\n--- Next message ---\n\n'.join(messages(digest)) + '\n')
    ranked, newest = report['ranking']['ranked'], report['ranking']['newest']
    summary = f'''# Synthetic evaluation results

**Scope:** authored synthetic samples and deterministic provider output. These results are not real-world AI accuracy or proof of better user relevance.

- Sample: {report['sample_size']} authored cases; {provided} have supplied content; 0 real Reels evaluated.
- Initial ready: {report['initial_ready']}; after retry: {report['ready_after_retry']}; link-only entries retained: {report['needs_content_after_retry']}.
- Supplied-input processing coverage: {report['ready_after_retry']}/{provided}. Total inbox ready fraction: {report['ready_after_retry']}/{report['sample_size']}.
- Reference evidence checks: {evidence_correct}/{evidence_total}; date-wording checks: {wording_correct}/{wording_total}. These compare fixture output against fixture labels, not Gemini output.
- Automatically created deadlines: {unexpected_due_dates}; confirmed dates require explicit user input.

| Ranking on the same {len(candidate_ids)} ready candidates | Precision@3 | nDCG@3 |
| --- | ---: | ---: |
| Revero | {ranked['precision']:.3f} | {ranked['ndcg']:.3f} |
| Newest first | {newest['precision']:.3f} | {newest['ndcg']:.3f} |

Ranked top three: {', '.join(report['ranking']['ranked_top3'])}.
Newest-first top three: {', '.join(report['ranking']['newest_top3'])}.

Precision counts grades above zero as relevant. nDCG uses gains `2^grade - 1`, discounted by `log2(position + 1)`, relative to the ideal ordering of this same candidate pool. Grades 0–3 were authored for interests {data['interests']}. This toy sample favors those interests and cannot establish real-world ranking improvement.

Duplicate detection, invalid-link rejection, failed extraction recovery, sourced retrieval, unsupported-question decline, and repeated-digest suppression were exercised. No external provider was contacted. The accompanying JSON records individual check outcomes.

Pending: collect 10–20 real Reels, review real provider output, complete seven days of use, and repeat the comparison using your relevance labels.
'''
    (output / 'synthetic-report.md').write_text(summary)
    return report


if __name__ == '__main__':
    report = run_benchmark(ROOT / 'evaluation/results')
    print(json.dumps({key: report[key] for key in ('sample_size','ready_after_retry','retry_recovered','ranking','external_provider_calls')}, indent=2))
