"""Expose ONLY this ASGI application to the tunnel."""
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from .instagram import MAX_BODY, initialize, intake, settings
from .main import DEFAULT_DB


def create_app(db_path=DEFAULT_DB, *, config=None):
    cfg = config or settings()

    @asynccontextmanager
    async def lifespan(app):
        initialize(db_path)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def safe_delivery_status(request: Request, call_next):
        response = await call_next(request)
        if request.method == 'POST' and request.url.path == '/webhooks/instagram':
            # Never log the URL/query, headers, request body, or provider identifiers.
            logging.getLogger('uvicorn.error').info('Instagram webhook POST status=%d', response.status_code)
        return response

    @app.get('/webhooks/instagram', response_class=PlainTextResponse)
    def challenge(request: Request):
        query = request.query_params
        if not cfg.verify_token:
            raise HTTPException(503, 'Webhook is not configured.')
        if (query.get('hub.mode') != 'subscribe' or not query.get('hub.challenge')
            or not hmac.compare_digest(query.get('hub.verify_token', '').encode(), cfg.verify_token.encode())):
            raise HTTPException(403, 'Verification rejected.')
        return query['hub.challenge']

    @app.post('/webhooks/instagram')
    async def receive(request: Request):
        if not cfg.app_secret or not cfg.account_id:
            raise HTTPException(503, 'Webhook is not configured.')
        signature = request.headers.get('x-hub-signature-256', '')
        if not re.fullmatch(r'sha256=[0-9a-fA-F]{64}', signature):
            raise HTTPException(403, 'Signature rejected.')
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                raise HTTPException(413, 'Webhook body too large.')
            body.extend(chunk)
        expected = hmac.new(cfg.app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature[7:].lower()):
            raise HTTPException(403, 'Signature rejected.')
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HTTPException(400, 'Invalid JSON.') from None
        await run_in_threadpool(intake, db_path, payload, cfg)
        return {'received': True}

    return app


app = create_app()
