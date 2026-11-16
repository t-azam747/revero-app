"""Repeatable isolated recovery drill. Authored data and fake providers only."""
from datetime import datetime,timezone
import argparse
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from fastapi.testclient import TestClient
from .storage import migrate,connect
from .backups import backup,restore,generate_key
from .main import create_app
from .extraction import run_one,claim,rate_settings
from .digest import run_digest,run_manual,DeliveryError,tick
from .instagram import run_one as reply,Config


class FixtureProvider:
    def extract(self,caption,*args):
        return {'summary':'Practice zebra joins.','topics':['SQLite'],'suggestions':[{'text':'Practice joins','source_index':0}],
                'date_candidates':[],'sources':[{'excerpt':caption,'origin':'caption','timestamp_seconds':None}]}


class FixtureSender:
    def __init__(self): self.sent=[]
    def send(self,text): self.sent.append(text); return len(self.sent)


class UncertainSender:
    def send(self,text): raise DeliveryError('Fixture ambiguous response',uncertain=True)


class NeverCall:
    def send(self,*args): raise AssertionError('Restored delivery must not call a provider.')


def drill(output):
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='revero-clean-restore-') as directory:
        root=Path(directory); original=root/'source'/'revero.sqlite3'; migrate(original)
        sender=FixtureSender()
        with TestClient(create_app(original)) as client:
            reel=client.post('/api/reels',json={'url':'https://instagram.com/reel/RestoreFixture/'}).json()
            job=client.post(f"/api/reels/{reel['id']}/content",data={'caption':'Practice zebra joins.'}).json()
            assert run_one(original,FixtureProvider())
            action=client.post('/api/actions',json={'job_id':job['id'],'suggestion_index':0}).json()
            assert client.patch(f"/api/actions/{action['id']}",json={'due_date':'2027-02-01'}).status_code==200
        assert run_digest(original,sender)['state']=='sent'
        assert run_manual(original,'fixture-manual',UncertainSender())['state']=='uncertain'
        with connect(original) as db:
            for index,state in enumerate(('sent','queued','sending'),1):
                db.execute('INSERT INTO instagram_inbound(id,account_id,mid,sender_id,event_at,received_at,kind) VALUES(?,?,?,?,?,?,?)',
                           (index,'100',str(index),'200',time.time(),time.time(),'reel'))
                db.execute('INSERT INTO instagram_outbox(id,inbound_id,state,provider_mid) VALUES(?,?,?,?)',(index,index,state,'fixture-confirmed' if state=='sent' else None))
            db.execute('UPDATE digest_preferences SET enabled=1,delivery_time=?',('20:45',))
        last_commit=time.time(); key=root/'recovery-key'; generate_key(key)
        encrypted=backup(original,root/'encrypted-spool',key)
        restored=root/'new-volume'/'revero.sqlite3'; restore_start=time.monotonic()
        restore(encrypted,restored,key)
        restore_seconds=time.monotonic()-restore_start
        assert not claim(restored,time.time(),rate_settings(),1)
        assert tick(restored,NeverCall()) is None
        assert not reply(restored,Config(account_id='100',sender_id='200',replies_enabled=True),NeverCall())
        try: run_digest(restored,NeverCall())
        except Exception as exc: assert getattr(exc,'status_code',None)==409
        else: raise AssertionError('Recovery delivery guard missing')
        password=secrets.token_urlsafe(32); password_file=root/'private-password'; password_file.write_text(password)
        environment={**os.environ,'REVERO_DB_PATH':str(restored),'REVERO_REQUIRE_MIGRATED':'true',
            'REVERO_PRIVATE_REQUIRED':'true','REVERO_PRIVATE_PASSWORD_FILE':str(password_file),
            'GEMINI_API_KEY':'','GEMINI_FREE_TIER_':'false','TELEGRAM_BOT_TOKEN':'','TELEGRAM_CHAT_ID':'',
            'INSTAGRAM_ACCESS_TOKEN':'','INSTAGRAM_REPLIES_ENABLED':'false'}
        with socket.socket() as free:
            free.bind(('127.0.0.1',0)); port=free.getsockname()[1]
        base='http://127.0.0.1:'+str(port)
        for _ in range(2):
            process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],
                    env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for attempt in range(100):
                    if process.poll() is not None: raise RuntimeError('Drill API failed startup.')
                    try:
                        if httpx.get(base+'/health',timeout=.2,trust_env=False).status_code==200: break
                    except httpx.HTTPError: pass
                    time.sleep(.05)
                else: raise RuntimeError('Drill API startup timed out.')
                assert httpx.get(base+'/api/reels',trust_env=False).status_code==401
                with httpx.Client(base_url=base,auth=('owner',password),headers={'X-Revero-Owner-Request':'1'},trust_env=False) as client:
                    assert len(client.get('/api/reels').json())==1
                    assert client.get('/api/search',params={'q':'zebra'}).json()['sources']
                    duplicate=client.post('/api/reels',json={'url':'https://instagram.com/reel/RestoreFixture/?again=1'}).json()
                    assert duplicate['created'] is False and duplicate['id']==reel['id']
                    assert client.get('/api/actions').json()[0]['due_date']=='2027-02-01'
                    prefs=client.get('/api/digest').json()['preferences']
                    assert prefs['delivery_time']=='20:45' and prefs['enabled'] is False
                    assert client.get('/api/operations').json()['controls']['delivery_paused']==1
            finally:
                process.terminate(); process.wait(timeout=10)
        with connect(restored) as db:
            assert db.execute('SELECT provider_mid FROM instagram_outbox WHERE id=1').fetchone()[0]=='fixture-confirmed'
            assert db.execute('SELECT state FROM instagram_outbox WHERE id=3').fetchone()[0]=='uncertain'
            assert db.execute('SELECT state FROM digest_runs').fetchone()[0]=='sent'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
        report={'scope':'Clean temporary volume and two real API starts; authored data and fake providers. Not a remote-host/off-host recovery claim.',
                'platform':platform.system(),'restore_seconds':restore_seconds,'known_fixture_snapshot_age_seconds':time.time()-last_commit,
                'elapsed_seconds':time.monotonic()-started,'checks':{'encryption_authenticated':True,'saves_preserved':True,'actions_preserved':True,
                'search_rebuilt':True,'schedule_preserved_but_disabled':True,'confirmed_message_ids_preserved':True,'inflight_sends_uncertain':True,
                'processing_and_delivery_paused':True,'private_api_authentication':True,'two_process_starts':True},
                'real_provider_calls':0,'remote_backup_verified':False,'production_RPO_RTO_demonstrated':False}
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(report,indent=2)+'\n')
    print('Isolated restore drill passed; no real provider calls.')
    return report


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,default=Path('artifacts/m1-restore-drill.json'))
    args=parser.parse_args(); drill(args.output)

if __name__=='__main__': main()
