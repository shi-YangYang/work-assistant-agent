"""Opt-in faults target a private TCP proxy and temporary media, never shared services."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
import errno
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.idempotency import Idempotency
from app.main import create_app
from app.modules.attachments.models import Attachment
from app.modules.work.models import WorkItem, WorkRevision
from test_full_system_acceptance import evidence

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('SPEC044_INFRASTRUCTURE_TEST') != '1',
    reason='Opt-in infrastructure faults require an isolated Spec044 schema',
)]


def isolated_url(settings):
    url = make_url(settings.database_url)
    assert url.database == 'paa_company_test' and url.host in ('127.0.0.1', 'localhost')
    assert re.fullmatch(r'-csearch_path=spec044_[a-z]+_[a-f0-9]{12}', url.query.get('options', ''))
    return url


@asynccontextmanager
async def database_proxy(url):
    """Only connections opened through this loopback listener can be interrupted."""
    writers, handlers = set(), set()
    state = SimpleNamespace(online=True, cut_connections=0)

    def cut():
        state.online = False
        state.cut_connections += len(writers)
        for writer in tuple(writers):
            writer.transport.abort()

    async def relay(reader, writer):
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()

    async def accept(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        upstream, pumps = None, []
        writers.add(writer)
        try:
            if not state.online:
                return
            incoming, upstream = await asyncio.open_connection(url.host, url.port or 5432)
            writers.add(upstream)
            if not state.online:
                return
            pumps = [asyncio.create_task(relay(reader, upstream)), asyncio.create_task(relay(incoming, writer))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionError, OSError):
            pass
        finally:
            for pump in pumps:
                pump.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for connection in (writer, upstream):
                if connection is not None:
                    writers.discard(connection)
                    connection.close()
                    try:
                        await connection.wait_closed()
                    except (ConnectionError, OSError):
                        pass
            handlers.discard(task)

    server = await asyncio.start_server(accept, '127.0.0.1', 0)
    state.port, state.cut = server.sockets[0].getsockname()[1], cut
    try:
        yield state
    finally:
        server.close()
        await server.wait_closed()
        cut()
        for handler in tuple(handlers):
            handler.cancel()
        await asyncio.gather(*tuple(handlers), return_exceptions=True)


def assert_private_failure(response, caplog, *, status, code, message, private_values=()):
    visible = response.text + caplog.text
    if any(value and value in visible for value in private_values):
        pytest.fail('Private infrastructure details appeared in the response or logs', pytrace=False)
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {'error'}
    assert body['error'] == {'code': code, 'message': message, 'requestId': response.headers['X-Request-ID']}
    assert not any(term in response.text for term in ('Traceback', 'SELECT ', 'INSERT ', 'postgresql', 'password'))


async def test_database_disconnect_rolls_back_partial_write_and_recovers(setup, caplog):
    settings, sessions, users, clients = setup
    url = isolated_url(settings)
    actor = users['employee']
    caplog.set_level('INFO', logger='uvicorn.error.paa_requests')
    async with database_proxy(url) as proxy:
        proxied_url = url.set(host='127.0.0.1', port=proxy.port).update_query_dict({'connect_timeout': '2'})
        local = replace(settings, database_url=proxied_url.render_as_string(hide_password=False))
        app = create_app(local)
        # Bound only this additional app's pool; the fixture/shared PostgreSQL is untouched.
        await app.state.sessions.kw['bind'].dispose()
        engine = create_async_engine(local.database_url, pool_size=2, max_overflow=0, pool_pre_ping=True)
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        inserted = []

        def cut_after_insert(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().startswith('INSERT INTO company_work_item'):
                inserted.append(True)
                proxy.cut()

        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                  headers=dict(clients['employee'].headers), cookies=clients['employee'].cookies)
        key, payload = str(uuid4()), {'title': '数据库断连后只保存一次', 'summary': '不可留下半条工作'}
        private = (local.database_url, clients['employee'].headers['X-CSRF-Token'])
        if url.password and len(url.password) > 4:
            private += (url.password,)
        try:
            async with app.router.lifespan_context(app), client:
                assert (await client.get('/api/v1/work-items')).status_code == 200
                event.listen(engine.sync_engine, 'after_cursor_execute', cut_after_insert)
                try:
                    interrupted = await asyncio.wait_for(client.post('/api/v1/work-items', json=payload,
                                                                     headers={'Idempotency-Key': key}), 10)
                finally:
                    event.remove(engine.sync_engine, 'after_cursor_execute', cut_after_insert)
                assert inserted == [True] and proxy.cut_connections >= 2
                assert_private_failure(interrupted, caplog, status=503, code='service_unavailable',
                                       message='服务暂不可用，请稍后重试', private_values=private)
                async with sessions() as db:
                    for model in (WorkItem, WorkRevision, Idempotency):
                        assert await db.scalar(select(func.count()).select_from(model).where(model.owner_id == actor.id)) == 0
                # A new request during the outage is finite and equally redacted.
                offline = await asyncio.wait_for(client.get('/api/v1/work-items'), 10)
                assert_private_failure(offline, caplog, status=503, code='service_unavailable',
                                       message='服务暂不可用，请稍后重试', private_values=private)
                proxy.online = True
                saved = await client.post('/api/v1/work-items', json=payload, headers={'Idempotency-Key': key})
                assert saved.status_code == 201, saved.text
                repeated = await client.post('/api/v1/work-items', json=payload, headers={'Idempotency-Key': key})
                assert repeated.status_code == 201 and repeated.json() == saved.json()
                detail = await client.get('/api/v1/work-items/' + saved.json()['id'])
                assert detail.status_code == 200 and detail.json()['summary'] == payload['summary']
                async with sessions() as db:
                    for model in (WorkItem, WorkRevision, Idempotency):
                        assert await db.scalar(select(func.count()).select_from(model).where(model.owner_id == actor.id)) == 1
                evidence('infrastructure-database', {'fault': 'owned TCP proxy disconnect after real INSERT, before commit',
                         'interruptedStatus': interrupted.status_code, 'offlineStatus': offline.status_code,
                         'partialRecords': 0, 'recoveredStatus': saved.status_code, 'works': 1, 'revisions': 1, 'receipts': 1})
        finally:
            await client.aclose()
            await engine.dispose()


@pytest.mark.parametrize('fault', ['permission', 'capacity'])
async def test_media_write_failure_leaves_no_file_or_row_and_recovers(setup, monkeypatch, caplog, fault):
    settings, sessions, users, clients = setup
    isolated_url(settings)
    client, actor = clients['employee'], users['employee']
    caplog.set_level('INFO', logger='uvicorn.error.paa_requests')
    original_open = Path.open
    marker = 'controlled-private-storage-detail-' + uuid4().hex
    attempted, partial = [], []
    initial_files = set(settings.media_dir.iterdir())

    @contextmanager
    def limited_file(path, *args, **kwargs):
        with original_open(path, *args, **kwargs) as target:
            def write(data):
                target.write(data[:3])
                target.flush()
                partial.append(path.stat().st_size)
                raise OSError(errno.ENOSPC, marker)
            yield SimpleNamespace(write=write)

    def unavailable(path, mode='r', *args, **kwargs):
        if path.parent == settings.media_dir and mode == 'xb':
            attempted.append(path)
            if fault == 'permission':
                raise PermissionError(errno.EACCES, marker)
            return limited_file(path, mode, *args, **kwargs)
        return original_open(path, mode, *args, **kwargs)

    content = b'controlled document content'
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', unavailable)
        failed = await client.post('/api/v1/uploads', files={'file': ('storage-test.txt', content, 'text/plain')})
    assert len(attempted) == 1
    assert partial == ([3] if fault == 'capacity' else [])
    assert_private_failure(failed, caplog, status=500, code='internal_error', message='服务处理失败，请稍后重试',
                           private_values=(marker, str(settings.media_dir)))
    assert set(settings.media_dir.iterdir()) == initial_files
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Attachment).where(Attachment.owner_id == actor.id)) == 0
    recovered = await client.post('/api/v1/uploads', files={'file': ('storage-test.txt', content, 'text/plain')})
    assert recovered.status_code == 201, recovered.text
    item = recovered.json()
    assert (await client.get(item['url'])).content == content
    assert (settings.media_dir / item['id']).read_bytes() == content
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Attachment).where(Attachment.owner_id == actor.id)) == 1
    evidence('infrastructure-media-' + fault, {'fault': fault, 'failedStatus': failed.status_code,
             'bytesWrittenBeforeFailure': sum(partial), 'orphanFiles': 0, 'partialRecords': 0,
             'recoveredStatus': recovered.status_code, 'attachments': 1})
