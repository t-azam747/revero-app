from concurrent.futures import ThreadPoolExecutor
import base64
import time
from fastapi.testclient import TestClient
import pytest
from app.main import create_app
from app.operations import worker_guard,status
from app.storage import migrate,connect


def test_private_workspace_authentication_and_csrf(tmp_path,monkeypatch):
    password='a-long-private-test-password-value'
    key=tmp_path/'password'; key.write_text(password)
    monkeypatch.setenv('REVERO_PRIVATE_PASSWORD_FILE',str(key))
    with TestClient(create_app(tmp_path/'db')) as client:
        assert client.get('/health').status_code==200
        assert client.get('/api/reels').status_code==401
        assert client.get('/api/operations').status_code==401
        auth={'Authorization':'Basic '+base64.b64encode(('owner:'+password).encode()).decode()}
        assert client.get('/api/reels',headers=auth).status_code==200
        assert client.post('/api/reels',headers=auth,json={'url':'https://instagram.com/reel/Auth/'}).status_code==403
        assert client.post('/api/reels',headers={**auth,'X-Revero-Owner-Request':'1'},json={'url':'https://instagram.com/reel/Auth/'}).status_code==200
        assert client.post('/api/reels',headers={**auth,'Origin':'https://untrusted.example'},json={'url':'https://instagram.com/reel/Auth/'}).status_code==403
        assert client.get('/api/operations',headers=auth).json()['schema_current']


def test_worker_ownership_and_heartbeat_survive_restart(tmp_path):
    path=tmp_path/'db'; migrate(path)
    with worker_guard(path,'scheduler'):
        for _ in range(50):
            if status(path)['workers']: break
            time.sleep(.01)
        assert status(path)['workers'][0]['healthy']
        with pytest.raises(RuntimeError,match='active owner'):
            with worker_guard(path,'scheduler'): pass
    with worker_guard(path,'scheduler'): pass


def test_provider_error_does_not_store_echoed_private_data(monkeypatch):
    import httpx
    from app.extraction import generate_json,ProviderError
    monkeypatch.setattr('app.extraction.httpx.post',lambda *a,**k:httpx.Response(400,json={'error':{'message':'sentinel-secret-and-private-source'}}))
    with pytest.raises(ProviderError) as error: generate_json([], {})
    assert 'sentinel' not in str(error.value)
    assert 'HTTP 400' in str(error.value)
