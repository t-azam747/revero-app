"""Local metadata/access experiment. Never sends credentials to attachment URLs."""
import ipaddress
import json
import logging
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import httpx
from .instagram import settings
from .extraction import connect, ROOT
from .main import DEFAULT_DB

MAX_BYTES = 20 * 1024 * 1024


def allowed(url):
    try:
        p = urlsplit(url)
        host = p.hostname or ''
        if p.scheme != 'https' or p.username or p.password or p.port not in (None,443): return False
        if not any(host.endswith('.'+suffix) for suffix in ('cdninstagram.com','fbcdn.net')): return False
        addresses = socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(row[4][0]).is_global for row in addresses)
    except (ValueError,OSError): return False


def inspect_reference(url):
    if not url or not allowed(url): return {'result':'reference_only','reason':'not_allowlisted_media_host'}
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='revero-access-') as directory:
            target=Path(directory)/'clip'
            with httpx.Client(timeout=10,trust_env=False,follow_redirects=False) as client:
                with client.stream('GET',url) as response:
                    if response.status_code != 200: return {'result':'unreadable','reason':'http_status','http_status':response.status_code}
                    if not response.headers.get('content-type','').split(';')[0].startswith('video/'): return {'result':'reference_only','reason':'not_video_content_type'}
                    total=0
                    with target.open('wb') as output:
                        for chunk in response.iter_raw(chunk_size=65536):
                            total+=len(chunk)
                            if total>MAX_BYTES or time.monotonic()-started>30: return {'result':'unreadable','reason':'download_limit'}
                            output.write(chunk)
            probe=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file','-show_entries','format=duration:stream=codec_type','-of','json',str(target)],capture_output=True,timeout=10)
            info=json.loads(probe.stdout)
            duration=float(info.get('format',{}).get('duration',0))
            if probe.returncode or duration<=0 or not any(s.get('codec_type')=='video' for s in info.get('streams',[])): return {'result':'unreadable','reason':'invalid_video'}
            decoded=subprocess.run(['ffmpeg','-v','error','-protocol_whitelist','file','-i',str(target),'-map','0:v:0','-f','null','-'],capture_output=True,timeout=30)
            if decoded.returncode: return {'result':'unreadable','reason':'decode_failed'}
            return {'result':'authorized_playable_video','bytes':total,'duration_seconds':duration}
    except Exception:
        return {'result':'unreadable','reason':'access_or_probe_failed'}


def main():
    logging.disable(logging.CRITICAL)
    cfg=settings()
    with connect(DEFAULT_DB) as db:
        rows=db.execute('''SELECT s.reel_id,s.reference,s.title FROM instagram_shares s JOIN instagram_inbound i ON i.id=s.inbound_id WHERE i.account_id=? AND i.sender_id=? ORDER BY s.inbound_id DESC''',(cfg.account_id,cfg.sender_id)).fetchall()
    seen=set(); results=[]
    for row in rows:
        if row['reel_id'] in seen: continue
        seen.add(row['reel_id'])
        result=inspect_reference(row['reference'])
        result.update(reel_id=row['reel_id'],title_available=bool(row['title']))
        results.append(result)
        print('sample_checked:',len(results),'result:',result['result'],flush=True)
    report={'scope':'Only directly supplied, allowlisted CDN references; no scraping or provider media discovery. Files deleted after probing.','samples':results,'unique_reels':len(results)}
    destination=ROOT/'evaluation/local/instagram-access-report.json'; destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,indent=2)); destination.chmod(0o600)
    print('report_written: evaluation/local/instagram-access-report.json')

if __name__=='__main__': main()
