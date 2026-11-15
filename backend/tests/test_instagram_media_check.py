from app.instagram_media_check import allowed, inspect_reference


def test_reject_untrusted_and_private_hosts(monkeypatch):
    for url in ('http://x.fbcdn.net/a','https://fbcdn.net.evil.test/a','https://127.0.0.1/a','https://user:secret@x.fbcdn.net/a','https://x.fbcdn.net:8080/a','https://instagram.com/reel/test/'):
        assert not allowed(url)
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    assert not allowed('https://x.fbcdn.net/a')
    assert inspect_reference('https://instagram.com/reel/test/')['result']=='reference_only'


def test_redirect_and_download_limit(monkeypatch):
    from app import instagram_media_check as module
    monkeypatch.setattr(module,'allowed',lambda url:True)
    class Response:
        status_code=302
        headers={'content-type':'video/mp4'}
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def iter_raw(self,**kwargs): yield b'x'*11
    response=Response()
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['follow_redirects'] is False
            assert kwargs['trust_env'] is False
            assert 'headers' not in kwargs
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def stream(self,*args): return response
    monkeypatch.setattr(module.httpx,'Client',Client)
    assert module.inspect_reference('https://x.fbcdn.net/a')['http_status']==302
    response.status_code=200
    monkeypatch.setattr(module,'MAX_BYTES',10)
    assert module.inspect_reference('https://x.fbcdn.net/a')['reason']=='download_limit'
