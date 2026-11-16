"""S3-compatible encrypted backup transport; keys and provider responses are never logged."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from .extraction import ROOT
from .storage import connect


def configuration():
    from dotenv import dotenv_values
    return {**dotenv_values(ROOT/'.env'),**os.environ}


def client_and_target():
    import boto3
    from botocore.config import Config
    values=configuration()
    endpoint=values.get('REVERO_BACKUP_S3_ENDPOINT','')
    url=urlsplit(endpoint)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Configure an HTTPS object-storage endpoint.')
    access=values.get('AWS_ACCESS_KEY_ID'); secret=values.get('AWS_SECRET_ACCESS_KEY')
    bucket=values.get('REVERO_BACKUP_S3_BUCKET'); region=values.get('REVERO_BACKUP_S3_REGION')
    prefix=values.get('REVERO_BACKUP_S3_PREFIX','revero/')
    if not all((access,secret,bucket,region)) or not re.fullmatch(r'[A-Za-z0-9/_-]+',prefix):
        raise ValueError('Object-storage configuration is incomplete.')
    for logger in ('botocore','boto3','urllib3','s3transfer'):
        logging.getLogger(logger).setLevel(logging.CRITICAL)
    client=boto3.client('s3',endpoint_url=endpoint,region_name=region,aws_access_key_id=access,aws_secret_access_key=secret,
                        config=Config(connect_timeout=10,read_timeout=30,retries={'max_attempts':2,'mode':'standard'}))
    return client,bucket,prefix.rstrip('/')+'/'


def upload_verified(database,artifact,client,bucket,prefix):
    artifact=Path(artifact)
    for file in (artifact,artifact.with_suffix('.json')):
        key=prefix+file.name
        content=file.read_bytes()
        client.put_object(Bucket=bucket,Key=key,Body=content)
        response=client.get_object(Bucket=bucket,Key=key)
        body=response['Body']
        try:
            # Bounded remote read; verify complete content, not just an ETag (multipart differs).
            downloaded=body.read(len(content)+1)
            if len(downloaded)!=len(content) or hashlib.sha256(downloaded).digest()!=hashlib.sha256(content).digest():
                raise ValueError('Remote backup verification failed.')
        finally: body.close()
    with connect(database) as db:
        db.execute("INSERT INTO operation_events(kind,created_at,outcome) VALUES('backup',?,'verified')",(time.time(),))


def prune(client,bucket,prefix,now=None):
    """Explicit opt-in only; apply the same retention buckets to dated, paired owned artifacts."""
    from datetime import datetime,timezone
    now=time.time() if now is None else now
    keys=[]
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=prefix):
        keys.extend(row['Key'] for row in page.get('Contents',[]))
    names=set(keys); kept=set(); delete=[]
    pattern=re.compile(re.escape(prefix)+r'revero-(\d{8}T\d{12}Z)-[a-f0-9]{32}\.rvbk$')
    for key in sorted(keys,reverse=True):
        match=pattern.fullmatch(key)
        if not match or key[:-5]+'.json' not in names: continue
        stamp=datetime.strptime(match[1],'%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc)
        age=now-stamp.timestamp()
        if age<0: continue
        if age<48*3600: slot=('hour',stamp.strftime('%Y%m%d%H'))
        elif age<30*86400: slot=('day',stamp.strftime('%Y%m%d'))
        elif age<84*86400: slot=('week',stamp.strftime('%G%V'))
        else: slot=None
        if slot is None or slot in kept: delete.extend([key,key[:-5]+'.json'])
        else: kept.add(slot)
    for key in delete: client.delete_object(Bucket=bucket,Key=key)
    return len(delete)//2
