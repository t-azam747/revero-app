"""Read-only evaluation of user-reviewed real saves; never invokes an external provider."""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import sys
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from .fixtures import ROOT
from .metrics import ranking_metrics
from app.digest import rank_reels
from app.main import DEFAULT_DB


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    reel_id: int | None = Field(default=None, gt=0)
    input_kind: Literal['caption', 'video', 'link_only'] | None = None
    relevance: int | None = Field(default=None, ge=0, le=3)
    link_sufficient: bool | None = None
    takeaway_correct: bool | None = None
    evidence_correct: bool | None = None
    dates_correct: bool | None = None
    expected_takeaway: str = ''
    expected_date_mentions: list[str] | None = None
    notes: str = ''


class Reviews(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interests: list[str] = Field(max_length=20)
    samples: list[Review]


def summarize_week(journal, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Kolkata')).date()
    days = set()
    for entry in journal.get('days', []):
        if not entry.get('date') or entry.get('used_app') is not True:
            continue
        recorded = date.fromisoformat(entry['date'])
        if recorded > today:
            raise ValueError('A future journal date cannot count as recorded use.')
        if recorded in days:
            raise ValueError('Duplicate journal dates cannot count twice.')
        days.add(recorded)
    span = (max(days)-min(days)).days+1 if days else 0
    return {'source': 'self-reported journal', 'recorded_use_days': len(days), 'calendar_span_days': span,
            'seven_days_recorded': len(days) >= 7 and span >= 7}


def evaluate_reviews(database, data, journal=None):
    reviews = Reviews.model_validate(data)
    samples = [sample for sample in reviews.samples if sample.reel_id is not None]
    identifiers = [sample.reel_id for sample in samples]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('Each real Reel must be reviewed once; duplicates are not separate samples.')
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError('The requested database does not exist.')
    with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = {row['id']: row for row in db.execute('''SELECT r.*, j.result, j.mime, j.state AS job_state FROM reels r
                    LEFT JOIN extraction_jobs j ON j.id=r.active_job''')}
    missing = set(identifiers)-rows.keys()
    if missing:
        raise ValueError(f'Review contains unknown Reel IDs: {sorted(missing)}')
    ready = [rows[identifier] for identifier in identifiers if rows[identifier]['status']=='ready' and rows[identifier]['job_state']=='ready' and rows[identifier]['result']]
    labels = {sample.reel_id: sample.relevance for sample in samples if sample.relevance is not None}
    ranking = None
    if ready and all(row['id'] in labels for row in ready):
        ranked = [row['id'] for row in rank_reels(ready, reviews.interests)]
        newest = [row['id'] for row in sorted(ready,key=lambda row:(row['created_at'],row['id']),reverse=True)]
        ranking = {'scope': 'Only ready, labeled Reels in this reviewed sample; not the entire inbox.',
                   'candidate_count':len(ready),'ranked_top3':ranked[:3],'newest_top3':newest[:3],
                   'ranked':ranking_metrics(ranked,labels),'newest':ranking_metrics(newest,labels)}
    wording_passed = wording_reviewed = 0
    for sample in samples:
        if sample.expected_date_mentions is None or not rows[sample.reel_id]['result']:
            continue
        actual = {item['original_text'] for item in json.loads(rows[sample.reel_id]['result'])['date_candidates']}
        wording_reviewed += 1
        wording_passed += actual == set(sample.expected_date_mentions)
    def judged(field):
        values = [getattr(sample,field) for sample in samples if getattr(sample,field) is not None]
        return {'passed':sum(values),'reviewed':len(values),'fraction':sum(values)/len(values) if values else None}
    status_counts = {}
    for identifier in identifiers:
        status=rows[identifier]['status']; status_counts[status]=status_counts.get(status,0)+1
    return {'scope':'User-reviewed local real-sample snapshot. No model calls, messages, content exports, or database writes.',
            'sample_size':len(samples),
            'supplied_content_counts':{kind:sum(sample.input_kind == kind for sample in samples) for kind in ('caption','video','link_only')},
            'unclassified_input_count':sum(sample.input_kind is None for sample in samples),'interests':reviews.interests,'status_counts':status_counts,
            'ready_count':len(ready),'processing_coverage':len(ready)/len(samples) if samples else None,
            'link_alone_sufficient':judged('link_sufficient'),'takeaway_correct':judged('takeaway_correct'),'evidence_correct':judged('evidence_correct'),
            'date_judgments_correct':judged('dates_correct'),
            'date_wording_exact_match':{'passed':wording_passed,'reviewed':wording_reviewed},
            'ranking':ranking,
            'ranking_pending_reason':None if ranking else 'Supply ready samples and relevance labels for every ready sample.',
            'week':summarize_week(journal or {}),
            'limitations':['Review labels are supplied by the user, not inferred by a model.',
                           'Date-wording matches do not measure automatic due-date resolution; dates require user confirmation.',
                           'Unreviewed values stay null; they are not counted as failures or successes.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviews',type=Path,default=ROOT/'evaluation/local/real-review.json')
    parser.add_argument('--journal',type=Path,default=ROOT/'evaluation/local/week-journal.json')
    parser.add_argument('--database',type=Path,default=DEFAULT_DB)
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/local/real-report.json')
    args=parser.parse_args()
    try:
        report=evaluate_reviews(args.database,json.loads(args.reviews.read_text()),
                                json.loads(args.journal.read_text()) if args.journal.exists() else None)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(f"Reviewed {report['sample_size']} real saves. Aggregate report: {args.output}")
    except (OSError,ValueError) as error:
        parser.exit(1,f'Evaluation could not run: {error}\n')


if __name__=='__main__': main()
