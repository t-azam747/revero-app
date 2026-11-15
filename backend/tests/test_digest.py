from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import threading

from fastapi.testclient import TestClient
import httpx
import pytest

from app.main import create_app
from app.extraction import run_one, connect
from app.digest import IST, build, messages, utf16_size, run_digest, tick, DeliveryError, TelegramMessenger, recover_uncertain

NIGHT = datetime(2026,1,2,17,30,tzinfo=timezone.utc)

class Provider:
    def extract(self, caption, *args):
        return {'summary': caption, 'topics': ['Learning'],
                'suggestions': [{'text':'Practice the lesson','source_index':0}], 'date_candidates':[],
                'sources':[{'excerpt':caption,'origin':'caption','timestamp_seconds':None}]}

class Messenger:
    def __init__(self): self.sent=[]; self.error=None
    def send(self,text):
        if self.error: raise self.error
        self.sent.append(text)
        return len(self.sent)

@pytest.fixture
def inbox(tmp_path):
    path=tmp_path/'digest.db'; sender=Messenger()
    with TestClient(create_app(path,messenger=sender)) as client:
        yield client,path,sender

def save(client,path,code,caption):
    row=client.post('/api/reels',json={'url':f'https://www.instagram.com/reel/{code}/'}).json()
    job=client.post(f"/api/reels/{row['id']}/content",data={'caption':caption}).json()
    assert run_one(path,Provider())
    with connect(path) as db:
        db.execute('UPDATE reels SET created_at=? WHERE id=?',(NIGHT.isoformat(),row['id']))
    return row,job

def test_rank_top_three_deadlines_and_pending_count(inbox):
    client,path,_=inbox
    rows=[]
    for index,text in enumerate(['SQLite backend interviews','Cooking soup','Travel planning','Gardening advice','Fitness practice']):
        rows.append(save(client,path,f'Rank{index}',text))
    response=client.put('/api/digest/preferences',json={'interests':['SQLite'],'enabled':False})
    assert response.status_code==200
    action=client.post('/api/actions',json={'job_id':rows[1][1]['id'],'suggestion_index':0}).json()
    client.patch(f"/api/actions/{action['id']}",json={'due_date':'2026-01-03'})
    client.post('/api/reels',json={'url':'https://www.instagram.com/reel/Pending/'})
    payload=build(path,NIGHT)
    assert len(payload['picks'])==3 and payload['picks'][0]['id']==rows[0][0]['id']
    assert payload['picks'][0]['reasons']['interest_matches']==['sqlite']
    assert payload['pending_count']==1
    assert payload['deadlines'][0]['id']==action['id']
    assert payload['deadlines'][0]['url'] not in [pick['url'] for pick in payload['picks']]
    client.patch(f"/api/actions/{action['id']}",json={'status':'done'})
    assert build(path,NIGHT)['deadlines']==[]
    assert build(path,NIGHT)==build(path,NIGHT)

def test_ist_schedule_same_day_catchup_and_duplicate_skip(inbox):
    client,path,sender=inbox
    client.put('/api/digest/preferences',json={'interests':[],'enabled':True})
    assert tick(path,sender,NIGHT-timedelta(seconds=1)) is None
    assert tick(path,sender,NIGHT)['state']=='sent'
    assert len(sender.sent)==1
    assert tick(path,sender,NIGHT+timedelta(minutes=10))['state']=='sent'
    assert len(sender.sent)==1
    with TestClient(create_app(path,messenger=sender)):
        assert tick(path,sender,NIGHT+timedelta(minutes=30))['state']=='sent'
    assert len(sender.sent)==1
    # No prior-date catch-up before the next night's scheduled time.
    assert tick(path,sender,NIGHT+timedelta(hours=2)) is None
    assert len(sender.sent)==1
    assert tick(path,sender,NIGHT+timedelta(days=1,minutes=15))['state']=='sent'
    assert len(sender.sent)==2

def test_manual_send_and_restart_do_not_duplicate(inbox):
    client,path,sender=inbox
    assert client.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='sent'
    assert client.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='sent'
    assert len(sender.sent)==1
    with TestClient(create_app(path,messenger=sender)) as restarted:
        assert restarted.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='sent'
    assert len(sender.sent)==1

def test_rate_limit_backoff(inbox):
    _,path,sender=inbox
    sender.error=DeliveryError('Rate limited',retry_after=60)
    assert run_digest(path,sender,NIGHT)['state']=='failed'
    sender.error=None
    assert run_digest(path,sender,NIGHT+timedelta(seconds=30))['state']=='failed'
    assert sender.sent==[]
    assert run_digest(path,sender,NIGHT+timedelta(seconds=60))['state']=='sent'

def test_uncertain_never_retries_without_review(inbox):
    client,path,sender=inbox
    sender.error=DeliveryError('Uncertain',uncertain=True)
    assert client.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='uncertain'
    sender.error=None
    assert client.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='uncertain'
    assert sender.sent==[]
    day=client.get('/api/digest').json()['manual_runs'][0]['run_id']
    assert client.post(f'/api/digest/manual/{day}/resolve',json={'decision':'not_delivered'}).json()['state']=='failed'
    assert client.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='sent'
    assert len(sender.sent)==1

def test_uncertain_confirmed_delivered_is_not_resent(inbox):
    client,path,sender=inbox
    sender.error=DeliveryError('Uncertain',uncertain=True)
    client.post('/api/digest/send',json={'request_id':'test-request'})
    day=client.get('/api/digest').json()['manual_runs'][0]['run_id']
    assert client.post(f'/api/digest/manual/{day}/resolve',json={'decision':'delivered'}).json()['state']=='sent'
    sender.error=None
    assert client.post('/api/digest/send',json={'request_id':'test-request'}).json()['state']=='sent'
    assert sender.sent==[]

def test_crashed_sending_is_uncertain_even_next_day(inbox):
    _,path,sender=inbox
    run_digest(path,sender,NIGHT)
    with connect(path) as db:
        db.execute("UPDATE digest_runs SET state='sending', started_at=?",(NIGHT.timestamp(),))
        db.execute("UPDATE digest_messages SET state='sending'")
    recover_uncertain(path,(NIGHT+timedelta(days=1)).timestamp())
    with connect(path) as db:
        assert db.execute('SELECT state FROM digest_runs').fetchone()[0]=='uncertain'
    assert run_digest(path,sender,NIGHT+timedelta(minutes=10))['state']=='uncertain'
    assert len(sender.sent)==1

def test_multiple_parts_resume_without_resending_successful_parts(inbox):
    client,path,sender=inbox
    reel,job=save(client,path,'Long','SQLite learning')
    for index in range(12):
        # Long, valid action snapshots exercise delivery pagination independently of extraction.
        with connect(path) as db:
            db.execute('''INSERT INTO actions(reel_id,job_id,suggestion_index,text,source_excerpt,source_origin,date_mentions,due_date)
                VALUES(?,?,?,?,?,'caption','[]','2026-01-03')''',(reel['id'],job['id'],index,'Long action '+('x'*900),'SQLite learning'))
    expected=messages(build(path,NIGHT))
    assert len(expected)>1 and all(utf16_size(text)<=4096 for text in expected)
    class Partial(Messenger):
        def send(self,text):
            if len(self.sent)==1: raise DeliveryError('Rate limited',retry_after=60)
            return super().send(text)
    partial=Partial()
    assert run_digest(path,partial,NIGHT)['state']=='failed'
    assert partial.sent==expected[:1]
    assert run_digest(path,sender,NIGHT+timedelta(seconds=60))['state']=='sent'
    assert sender.sent==expected[1:]

def test_concurrent_claim_does_not_double_send(inbox):
    _,path,_=inbox
    entered=threading.Event(); release=threading.Event()
    class Blocking(Messenger):
        def send(self,text):
            entered.set(); assert release.wait(5)
            return super().send(text)
    sender=Blocking()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run_digest,path,sender,NIGHT)
        assert entered.wait(5)
        second=pool.submit(run_digest,path,sender,NIGHT).result()
        assert second['state']=='sending'
        release.set()
        assert first.result()['state']=='sent'
    assert len(sender.sent)==1

def test_telegram_transport_error_classification(monkeypatch):
    monkeypatch.setattr('app.digest.configuration',lambda:{'TELEGRAM_BOT_TOKEN':'123:test','TELEGRAM_CHAT_ID':'456'})
    def success(url,**kwargs):
        assert url.endswith('/sendMessage')
        assert kwargs['json']['chat_id']=='456' and 'parse_mode' not in kwargs['json']
        return httpx.Response(200,json={'ok':True,'result':{'message_id':7}})
    monkeypatch.setattr('app.digest.httpx.post',success)
    assert TelegramMessenger().send('Hello')==7
    def timeout(*args,**kwargs): raise httpx.ReadTimeout('must not log credential URLs')
    monkeypatch.setattr('app.digest.httpx.post',timeout)
    with pytest.raises(DeliveryError) as exc: TelegramMessenger().send('Hello')
    assert exc.value.uncertain
    monkeypatch.setattr('app.digest.httpx.post',lambda *a,**k:httpx.Response(429,json={'ok':False,'parameters':{'retry_after':99}}))
    with pytest.raises(DeliveryError) as exc: TelegramMessenger().send('Hello')
    assert not exc.value.uncertain and exc.value.retry_after==99

def test_preview_and_preferences_without_telegram(tmp_path,monkeypatch):
    monkeypatch.setattr('app.digest.telegram_configured',lambda:False)
    with TestClient(create_app(tmp_path/'db')) as client:
        assert client.get('/api/digest').status_code==200
        assert client.post('/api/digest/send',json={'request_id':'test-request'}).status_code==503
        assert client.put('/api/digest/preferences',json={'interests':['cooking'],'enabled':True}).status_code==400
        assert client.put('/api/digest/preferences',json={'interests':['cooking'],'enabled':False}).status_code==200
        assert client.put('/api/digest/preferences',json={'interests':[''],'enabled':False}).status_code==422


def test_stale_worker_cannot_overwrite_uncertain_delivery(inbox):
    _,path,_=inbox
    class Stale(Messenger):
        def send(self,text):
            recover_uncertain(path,NIGHT.timestamp()+121)
            return 123
    assert run_digest(path,Stale(),NIGHT)['state']=='uncertain'
    with connect(path) as db:
        assert db.execute('SELECT state FROM digest_runs').fetchone()[0]=='uncertain'
        assert db.execute('SELECT state FROM digest_messages').fetchone()[0]=='uncertain'


def test_retry_keeps_frozen_digest_snapshot(inbox):
    client,path,sender=inbox
    reel,job=save(client,path,'Frozen','Original SQLite lesson.')
    sender.error=DeliveryError('Connection failed',retry_after=60)
    run_digest(path,sender,NIGHT)
    client.post(f"/api/reels/{reel['id']}/content",data={'caption':'A completely new cooking lesson.'})
    run_one(path,Provider())
    sender.error=None
    run_digest(path,sender,NIGHT+timedelta(seconds=60))
    assert 'Original SQLite lesson.' in sender.sent[0]
    assert 'new cooking' not in sender.sent[0]


def test_emoji_messages_stay_within_telegram_utf16_limit():
    payload={'local_date':'2026-01-01','picks':[{'summary':'🌱'*1000,'url':'https://example.com'} for _ in range(3)],
             'deadlines':[{'due_date':'2026-01-01','text':'🌱'*1000,'url':'https://example.com'} for _ in range(10)],'pending_count':1}
    parts=messages(payload)
    assert len(parts)>1 and all(utf16_size(part)<=4096 for part in parts)


def test_chat_id_helper_reads_only_private_chats_without_printing_token(monkeypatch,capsys):
    from app import telegram_setup
    monkeypatch.setattr('app.telegram_setup.configuration',lambda:{'TELEGRAM_BOT_TOKEN':'123:private-test-token'})
    monkeypatch.setattr('app.telegram_setup.httpx.get',lambda *a,**k:httpx.Response(200,json={'ok':True,'result':[
        {'message':{'chat':{'id':456,'type':'private'}}}, {'message':{'chat':{'id':-789,'type':'group'}}}]}))
    assert telegram_setup.main()==0
    output=capsys.readouterr().out
    assert '456' in output and '-789' not in output and 'private-test-token' not in output
    def fail(*args,**kwargs): raise httpx.ConnectError('https://api.telegram.org/bot123:private-test-token')
    monkeypatch.setattr('app.telegram_setup.httpx.get',fail)
    assert telegram_setup.main()==1
    assert 'private-test-token' not in capsys.readouterr().out


def test_time_change_restart_and_manual_does_not_consume_schedule(inbox):
    client,path,sender=inbox
    assert client.get('/api/digest').json()['preferences']['delivery_time']=='23:00'
    assert client.put('/api/digest/preferences',json={'interests':[],'enabled':True,'delivery_time':'23:30'}).status_code==200
    assert tick(path,sender,NIGHT) is None
    manual=client.post('/api/digest/send',json={'request_id':'first'}).json()
    assert manual['state']=='sent'
    with connect(path) as db:
        assert db.execute('SELECT count(*) FROM digest_runs').fetchone()[0]==0
    with TestClient(create_app(path,messenger=sender)) as restarted:
        assert restarted.get('/api/digest').json()['preferences']['delivery_time']=='23:30'
        # Same running scheduler observes the saved change on its next tick.
        restarted.put('/api/digest/preferences',json={'interests':[],'enabled':True,'delivery_time':'22:00'})
        assert tick(path,sender,NIGHT)['state']=='sent'
        restarted.put('/api/digest/preferences',json={'interests':[],'enabled':True,'delivery_time':'23:15'})
        assert tick(path,sender,NIGHT+timedelta(minutes=20))['state']=='sent'
        assert len(sender.sent)==2
        assert restarted.post('/api/digest/send',json={'request_id':'first'}).json()['state']=='sent'
        assert len(sender.sent)==2
        assert restarted.post('/api/digest/send',json={'request_id':'second'}).json()['state']=='sent'
        assert len(sender.sent)==3


@pytest.mark.parametrize('value',['24:00','1:00','23:60','09:30:00','',None])
def test_invalid_schedule_time(inbox,value):
    client,_,_=inbox
    assert client.put('/api/digest/preferences',json={'interests':[],'enabled':False,'delivery_time':value}).status_code==422


def test_manual_concurrent_distinct_clicks_share_one_run(inbox):
    from app.digest import run_manual
    _,path,_=inbox
    entered=threading.Event(); release=threading.Event()
    class Blocking(Messenger):
        def send(self,text):
            entered.set(); assert release.wait(5)
            return super().send(text)
    sender=Blocking()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run_manual,path,'click-a',sender,NIGHT)
        assert entered.wait(5)
        second=run_manual(path,'click-b',sender,NIGHT)
        assert second['state']=='sending'
        release.set()
        assert first.result()['run_id']==second['run_id']
    assert run_manual(path,'click-b',sender,NIGHT)['state']=='sent'
    assert len(sender.sent)==1


def test_today_boundary_all_readable_and_pending(inbox):
    client,path,_=inbox
    rows=[save(client,path,f'Daily{i}',f'Lesson {i}')[0] for i in range(6)]
    with connect(path) as db:
        # India midnight is 18:30 UTC on the previous date.
        db.execute('UPDATE reels SET created_at=? WHERE id=?',('2026-01-01T18:29:59Z',rows[0]['id']))
        db.execute('UPDATE reels SET created_at=? WHERE id=?',('2026-01-01T18:30:00Z',rows[1]['id']))
    client.post('/api/reels',json={'url':'https://instagram.com/reel/UnreadableDaily/'})
    payload=build(path,NIGHT)
    assert payload['readable_count']==5 and len(payload['picks'])==3
    assert payload['unreadable_count']==1
    rendered='\n'.join(messages(payload))
    assert 'Lesson 0' not in rendered
    assert all(f'Lesson {i}' in rendered for i in range(1,6))
