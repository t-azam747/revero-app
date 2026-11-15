from copy import deepcopy
from fastapi.testclient import TestClient
import pytest
from app.main import create_app
from app.extraction import run_one, ProviderError, connect
from app.search import retrieve, NO_MATCH

class Provider:
    def extract(self, caption, *args):
        return {'summary': caption, 'topics': ['Learning'], 'suggestions': [], 'date_candidates': [],
                'sources': [{'excerpt': caption, 'origin': 'caption', 'timestamp_seconds': None}]}

class Answerer:
    def __init__(self): self.calls = 0
    def answer(self, question, sources):
        self.calls += 1
        return {'claims': [{'text': 'Practice SQLite joins for backend interviews.', 'source_ids': [sources[0]['id']]}]}

@pytest.fixture
def inbox(tmp_path):
    path=tmp_path/'search.db'; answerer=Answerer()
    with TestClient(create_app(path, answerer=answerer)) as client:
        yield client, path, answerer

def save(client, path, code, caption):
    reel=client.post('/api/reels',json={'url': f'https://www.instagram.com/reel/{code}/'}).json()
    client.post(f"/api/reels/{reel['id']}/content",data={'caption':caption})
    run_one(path, Provider())
    return reel

def test_older_reel_retrieval_and_grounded_answer(inbox):
    client,path,answerer=inbox
    old=save(client,path,'Old','Practice SQLite joins for backend interviews.')
    save(client,path,'New','Roast carrots in the oven.')
    response=client.post('/api/ask',json={'question':'What did I save about backend interviews?'}).json()
    assert response['status']=='answered' and answerer.calls==1
    assert response['sources'][0]['reel_id']==old['id']
    assert response['sources'][0]['url']==old['url']
    assert response['claims'][0]['source_ids']==[response['sources'][0]['id']]
    with TestClient(create_app(path,answerer=answerer)) as restarted:
        assert restarted.get('/api/search?q=interview').json()['sources'][0]['reel_id']==old['id']

def test_no_match_never_calls_provider(inbox):
    client,path,answerer=inbox
    save(client,path,'Food','Roast carrots.')
    for question in ['quantum physics','what did I save?', '\" OR NEAR(*); --']:
        result=client.post('/api/ask',json={'question':question}).json()
        assert result['answer']==NO_MATCH and result['sources']==[]
    assert answerer.calls==0

def test_index_tracks_revisions_and_captions_before_extraction(inbox):
    client,path,_=inbox
    reel=save(client,path,'Version','Practice backend interviews.')
    assert retrieve(path,'backend')
    client.post(f"/api/reels/{reel['id']}/content",data={'caption':'Learn sourdough recipes.'})
    assert not retrieve(path,'backend')
    assert retrieve(path,'sourdough')[0]['origin']=='caption'
    run_one(path,Provider())
    assert retrieve(path,'recipes')

@pytest.mark.parametrize('raw', [{'claims':[{'text':'Invented','source_ids':['fake']}]}, {'claims':[{'text':'No citation','source_ids':[]}]}, {'claims':[{'text':'Bad','source_ids':['fake'],'url':'https://evil.example'}]}])
def test_invalid_citations_rejected(inbox,raw):
    client,path,answerer=inbox
    save(client,path,'Evidence','Practice SQLite joins.')
    answerer.answer=lambda *args: raw
    assert client.post('/api/ask',json={'question':'SQLite'}).status_code==502

def test_provider_declines_and_quota(inbox):
    client,path,answerer=inbox
    save(client,path,'Evidence','Practice SQLite joins.')
    answerer.answer=lambda *args: {'claims':[]}
    assert client.post('/api/ask',json={'question':'SQLite'}).json()['status']=='no_match'
    def quota(*args): raise ProviderError('Quota',quota=True)
    answerer.answer=quota
    assert client.post('/api/ask',json={'question':'SQLite'}).json()['status']=='deferred'
    answerer.answer=lambda *args: pytest.fail('Provider called during cooldown')
    assert client.post('/api/ask',json={'question':'SQLite'}).json()['status']=='deferred'

def test_unconfigured_returns_evidence_without_fabricated_answer(tmp_path,monkeypatch):
    monkeypatch.setattr('app.search.configured',lambda:False)
    path=tmp_path/'db'
    with TestClient(create_app(path)) as client:
        save(client,path,'Local','SQLite interview practice.')
        data=client.post('/api/ask',json={'question':'SQLite'}).json()
        assert data['status']=='unconfigured' and data['claims']==[] and data['sources']
        assert client.post('/api/ask',json={'question':'  '}).status_code==422
