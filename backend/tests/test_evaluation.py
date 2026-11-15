from datetime import date
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from evaluation.benchmark import run_benchmark
from evaluation.fixtures import FixtureAnswerer, FixtureMessenger, seed
from evaluation.metrics import ranking_metrics
from evaluation.real_review import evaluate_reviews, summarize_week
from app.main import create_app


def test_ranking_metrics_use_same_pool_and_correct_discounts():
    labels={1:3,2:2,3:0}
    assert ranking_metrics([1,2,3],labels)['ndcg']==1
    reversed_result=ranking_metrics([3,2,1],labels)
    assert 0 < reversed_result['ndcg'] < 1
    assert reversed_result['precision']==2/3
    assert ranking_metrics([],labels)=={'k':0,'precision':None,'ndcg':None}
    assert ranking_metrics([3],labels)['ndcg'] is None
    with pytest.raises(ValueError): ranking_metrics([1,1],labels)
    with pytest.raises(ValueError): ranking_metrics([4],labels)
    with pytest.raises(ValueError): ranking_metrics([1],{1:True})


def test_synthetic_benchmark_is_reproducible_without_network(tmp_path):
    with patch('httpx.post',side_effect=AssertionError('External calls forbidden in synthetic evaluation')):
        first=run_benchmark(tmp_path/'first')
        second=run_benchmark(tmp_path/'second')
    assert first==second
    assert first['sample_size']==16 and first['real_reel_sample_size']==0
    assert first['initial_ready']==13 and first['ready_after_retry']==14
    assert first['retry_recovered'] and first['duplicate_same_id'] and first['invalid_link_rejected']
    assert first['external_provider_calls']==0 and first['digest_rerun_no_duplicate']
    assert first['reference_evidence_checks']=={'passed':14,'total':14}
    assert first['reference_date_wording_checks']=={'passed':2,'total':2}
    assert first['automatically_created_deadlines']==0
    assert first['ranking']['candidate_count']==14


def test_real_review_is_read_only_and_nulls_are_unmeasured(tmp_path):
    path=tmp_path/'db'
    with TestClient(create_app(path,answerer=FixtureAnswerer(),messenger=FixtureMessenger())) as client:
        ids,_=seed(client,path,retry=True)
    before=path.read_bytes()
    result=evaluate_reviews(path,{'interests':['SQLite'],'samples':[
        {'reel_id':ids['sqlite-joins'],'relevance':3,'evidence_correct':True,'expected_date_mentions':[]},
        {'reel_id':ids['link-only'],'input_kind':'link_only'},
        {'reel_id':None}]})
    assert path.read_bytes()==before
    assert result['sample_size']==2 and result['ready_count']==1
    assert result['link_alone_sufficient']['fraction'] is None
    assert result['evidence_correct']=={'passed':1,'reviewed':1,'fraction':1.0}
    assert result['ranking']['candidate_count']==1
    assert result['week']['recorded_use_days']==0
    with pytest.raises(ValueError): evaluate_reviews(path,{'interests':[],'samples':[{'reel_id':9999}]})
    with pytest.raises(ValueError): evaluate_reviews(path,{'interests':[],'samples':[{'reel_id':ids['sqlite-joins']},{'reel_id':ids['sqlite-joins']}]})


def test_week_placeholders_future_days_and_duplicate_dates_do_not_fake_usage():
    assert not summarize_week({'days':[{'date':None,'used_app':False} for _ in range(7)]})['seven_days_recorded']
    data={'days':[{'date':f'2026-01-{day:02d}','used_app':True} for day in range(1,8)]}
    assert summarize_week(data,today=date(2026,1,7))['seven_days_recorded']
    with pytest.raises(ValueError): summarize_week(data,today=date(2026,1,6))
    with pytest.raises(ValueError): summarize_week({'days':[data['days'][0],data['days'][0]]})
