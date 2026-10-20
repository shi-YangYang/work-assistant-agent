"""Admission guards release multipart files and capacity after every failure."""
import asyncio
import errno
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, UploadFile
from starlette import formparsers
from app.http.middleware import BodyLimit, Boundaries

pytestmark = pytest.mark.asyncio


def application(handler):
    app = FastAPI()
    app.state.settings = SimpleNamespace(web_origin='http://test')
    app.post('/api/v1/uploads')(handler)
    app.add_middleware(BodyLimit)
    app.add_middleware(Boundaries)
    return app


async def test_streamed_limit_closes_spooled_files_and_accepts_next_request(monkeypatch):
    from app.http import middleware
    monkeypatch.setattr(middleware, 'MAX_UPLOAD_BODY_BYTES', 4096)
    opened = []
    original = formparsers.SpooledTemporaryFile
    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        opened.append(result)
        return result
    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', tracked)
    async def handler(file: UploadFile):
        return {'size': len(await file.read())}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(handler)), base_url='http://test', headers={'Origin': 'http://test'}) as client:
        async def stream():
            yield b'--sample\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\n'
            yield b'x' * 3000
            yield b'y' * 3000
            yield b'\r\n--sample--\r\n'
        rejected = await client.post('/api/v1/uploads', content=stream(), headers={'Content-Type': 'multipart/form-data; boundary=sample'})
        assert rejected.status_code == 413, rejected.text
        assert opened and all(item.closed for item in opened)
        response = await client.post('/api/v1/uploads', files={'file': ('ok.txt', b'ok')})
        assert response.json() == {'size': 2}
        before = len(opened)
        response = await client.post('/api/v1/uploads', content=b'x' * 4097)
        assert response.status_code == 413 and len(opened) == before


async def test_other_routes_keep_their_smaller_body_limit(monkeypatch):
    from app.http import middleware
    monkeypatch.setattr(middleware, 'MAX_REQUEST_BODY_BYTES', 1024)
    async def handler(file: UploadFile):
        return {'ok': True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(handler)), base_url='http://test', headers={'Origin': 'http://test'}) as client:
        response = await client.post('/api/v1/messages', content=b'x' * 1025)
        assert response.status_code == 413


async def test_upload_capacity_rejects_excess_but_releases_after_cancellation(monkeypatch):
    from app.http import middleware
    monkeypatch.setattr(middleware, 'MAX_CONCURRENT_UPLOADS', 1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(file: UploadFile):
        entered.set()
        await release.wait()
        return {'ok': True}
    app = application(handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://test'}) as client:
        active = asyncio.create_task(client.post('/api/v1/uploads', files={'file': ('a.txt', b'a')}))
        await asyncio.wait_for(entered.wait(), 3)
        response = await client.post('/api/v1/uploads', files={'file': ('b.txt', b'b')})
        assert response.status_code == 429 and response.headers['Retry-After'] == '2'
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        release.set()
        assert (await client.post('/api/v1/uploads', files={'file': ('c.txt', b'c')})).status_code == 200


async def test_storage_pressure_and_disk_error_are_safe_and_recoverable(monkeypatch):
    from app.http import middleware
    broken = True
    async def handler(file: UploadFile):
        if broken:
            raise OSError(errno.ENOSPC, 'private disk path')
        return {'ok': True}
    app = application(handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://test'}) as client:
        with monkeypatch.context() as patch:
            patch.setattr(middleware.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
            response = await client.post('/api/v1/uploads', files={'file': ('a.txt', b'a')})
            assert response.status_code == 507 and '空间不足' in response.text
        response = await client.post('/api/v1/uploads', files={'file': ('a.txt', b'a')})
        assert response.status_code == 507 and 'private disk path' not in response.text
        broken = False
        assert (await client.post('/api/v1/uploads', files={'file': ('a.txt', b'a')})).status_code == 200
