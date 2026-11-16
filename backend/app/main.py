from contextlib import asynccontextmanager
from pathlib import Path
import re
import os
import base64
import hmac
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from . import extraction, actions, search, digest, library
from pydantic import BaseModel

DEFAULT_DB = Path(os.environ.get('REVERO_DB_PATH', Path(__file__).resolve().parents[1] / 'data' / 'revero.sqlite3')).resolve()


class ReelInput(BaseModel):
    url: str


def canonicalize(url: str) -> tuple[str, str]:
    message = 'Enter an HTTPS Instagram Reel link, like https://www.instagram.com/reel/AbC123/.'
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise HTTPException(400, message)
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == 'https' and parts.netloc in {'www.instagram.com', 'instagram.com'})
        match = re.fullmatch(r'/reel/([A-Za-z0-9_-]+)/?', parts.path)
    except ValueError:
        raise HTTPException(400, message)
    if not valid or not match:
        raise HTTPException(400, message)
    shortcode = match.group(1)
    return shortcode, f'https://www.instagram.com/reel/{shortcode}/'


def initialize_database(db_path):
    from .storage import initialize
    initialize(db_path)


def create_app(db_path: Path = DEFAULT_DB, *, answerer=None, messenger=None) -> FastAPI:
    db_path = Path(db_path).resolve()

    def connect():
        return extraction.connect(db_path)

    @asynccontextmanager
    async def lifespan(app):
        initialize_database(db_path)
        yield

    app = FastAPI(title='Revero', lifespan=lifespan)

    # Optional host-level owner credential for deployment; localhost development stays compatible.
    password_file = os.environ.get('REVERO_PRIVATE_PASSWORD_FILE')
    private_password = Path(password_file).read_text().strip() if password_file else None
    if private_password is not None and len(private_password) < 24:
        raise RuntimeError('Private workspace password must contain at least 24 characters.')
    if os.environ.get('REVERO_PRIVATE_REQUIRED') == 'true' and private_password is None:
        raise RuntimeError('Private workspace credentials are required.')

    @app.middleware('http')
    async def owner_access(request: Request, call_next):
        if private_password is not None and request.url.path != '/health':
            authenticated = False
            try:
                scheme, encoded = request.headers.get('Authorization','').split(' ',1)
                user, supplied = base64.b64decode(encoded,validate=True).decode().split(':',1)
                authenticated = scheme.lower() == 'basic' and user == 'owner' and hmac.compare_digest(supplied.encode(),private_password.encode())
            except (ValueError,UnicodeError):
                pass
            if not authenticated:
                return Response(status_code=401,headers={'WWW-Authenticate':'Basic realm="Revero", charset="UTF-8"'})
            if request.method not in ('GET','HEAD','OPTIONS'):
                origin = request.headers.get('Origin')
                expected_origin = str(request.base_url).rstrip('/')
                if (origin and origin != expected_origin) or (not origin and request.headers.get('X-Revero-Owner-Request') != '1'):
                    return Response(status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="frame-ancestors 'none'"
        return response

    @app.get('/health')
    def health():
        with connect() as db:
            db.execute('SELECT 1 FROM schema_migrations LIMIT 1').fetchone()
        return {'ready':True}

    @app.get('/api/operations')
    def operations_status():
        from .operations import status
        return status(db_path)
    app.include_router(actions.router(db_path))
    app.include_router(search.router(db_path, answerer))
    app.include_router(digest.router(db_path, messenger))

    @app.post('/api/reels')
    def save_reel(payload: ReelInput):
        shortcode, url = canonicalize(payload.url)
        with connect() as db:
            row, created = library.save(db, shortcode, url)
        return {**dict(row), 'created': created}

    @app.get('/api/reels')
    def list_reels():
        with connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM reels ORDER BY id')]

    @app.get('/api/processing')
    def processing_config():
        return {'configured': extraction.configured(), 'max_video_bytes': extraction.MAX_VIDEO,
                'message': 'Processing requires a free-tier Gemini project with billing disabled. Free-tier inputs may be used by Google to improve products.'}

    @app.get('/api/reels/{reel_id}/content')
    def content(reel_id: int):
        with connect() as db:
            reel = db.execute('SELECT * FROM reels WHERE id=?', (reel_id,)).fetchone()
            if not reel:
                raise HTTPException(404, 'Reel not found.')
            job = db.execute('SELECT * FROM extraction_jobs WHERE id=?', (reel['active_job'],)).fetchone()
        return {'reel': dict(reel), 'job': extraction.public_job(job)}

    @app.post('/api/reels/{reel_id}/content')
    async def add_content(reel_id: int, request: Request):
        # Bound the entire multipart body before the parser can spool unbounded data.
        maximum = extraction.MAX_VIDEO + 100000
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > maximum:
                raise HTTPException(413, 'Upload exceeds 10 MiB. Choose a smaller clip.')
        request._body = bytes(body)
        async with request.form(max_files=1, max_fields=1, max_part_size=100000) as form:
            caption = form.get('caption', '')
            video = form.get('video')
            if not isinstance(caption, str) or len(caption) > extraction.MAX_CAPTION:
                raise HTTPException(400, 'Caption must be at most 20,000 characters.')
            caption = caption.strip()
            media, mime = None, None
            if video is not None:
                if not hasattr(video, 'read'):
                    raise HTTPException(400, 'Attach a supported video file.')
                media = await video.read(extraction.MAX_VIDEO + 1)
                mime = video.content_type
                if len(media) > extraction.MAX_VIDEO:
                    raise HTTPException(413, 'Upload exceeds 10 MiB. Choose a smaller clip.')
                valid_mp4 = mime in {'video/mp4', 'video/quicktime'} and len(media) >= 12 and media[4:8] == b'ftyp'
                valid_webm = mime == 'video/webm' and media.startswith(bytes.fromhex('1a45dfa3'))
                if not (valid_mp4 or valid_webm):
                    raise HTTPException(400, 'Choose an MP4, MOV, or WebM video with a valid file header.')
            if not caption and not media:
                raise HTTPException(400, 'Add a caption or attach a small video first.')
            job = extraction.attach(db_path, reel_id, caption, media, mime)
        if job is None:
            raise HTTPException(404, 'Reel not found.')
        return job

    @app.post('/api/reels/{reel_id}/retry')
    def retry(reel_id: int):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT j.* FROM extraction_jobs j JOIN reels r ON r.active_job=j.id WHERE r.id=?', (reel_id,)).fetchone()
            if not job:
                raise HTTPException(404, 'Add content to this Reel first.')
            if job['state'] == 'failed':
                db.execute("UPDATE extraction_jobs SET state='queued', attempts=0, error=NULL, available_at=0 WHERE id=?", (job['id'],))
                db.execute("UPDATE reels SET status='queued' WHERE id=?", (reel_id,))
            elif job['state'] == 'queued' and job['available_at'] > time.time():
                raise HTTPException(409, 'This job is deferred. Wait for the automatic retry to protect your quota.')
            row = db.execute('SELECT * FROM extraction_jobs WHERE id=?', (job['id'],)).fetchone()
        return extraction.public_job(row)

    @app.post('/api/reels/{reel_id}/process')
    def process_now(reel_id: int):
        """Manual override: clear backoff and prioritize. The worker still needs a free token."""
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT j.* FROM extraction_jobs j JOIN reels r ON r.active_job=j.id WHERE r.id=?', (reel_id,)).fetchone()
            if not job:
                raise HTTPException(404, 'Add content to this Reel first.')
            if job['state'] == 'processing':
                raise HTTPException(409, 'This Reel is already processing.')
            if job['state'] != 'ready':
                db.execute('''UPDATE extraction_jobs SET state='queued', attempts=0, error=NULL,
                              available_at=0, lease_until=NULL, priority=1 WHERE id=?''', (job['id'],))
                db.execute("UPDATE reels SET status='queued' WHERE id=?", (reel_id,))
            row = db.execute('SELECT * FROM extraction_jobs WHERE id=?', (job['id'],)).fetchone()
        return extraction.public_job(row)

    frontend_dir = os.environ.get('REVERO_FRONTEND_DIR')
    if frontend_dir:
        app.mount('/',StaticFiles(directory=frontend_dir,html=True),name='workspace')
    return app


app = create_app()
