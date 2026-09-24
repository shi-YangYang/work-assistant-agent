import asyncio
import httpx
import json
import logging
import pytest
from datetime import timedelta
from fastapi.responses import StreamingResponse
from paa_server.api import create_app
from paa_server.db.base import now
from paa_server.modules.members.models import Member
from paa_server.modules.support.models import SupportFeedback
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from uuid import uuid4


def payload(description='发送消息时遇到问题'):
    return {'description': description, 'diagnostics': {
        'occurredAt': '2026-09-16T08:00:00Z', 'page': '/assistant/:conversationId',
        'category': 'server', 'httpStatus': 503, 'requestId': str(uuid4()),
        'appVersion': '0.1.0', 'browser': 'Safari 26.0', 'os': 'iOS 26.0',
        'viewport': '390x844',
    }}


async def submit(client, body=None, key=None):
    response = await client.post('/api/v1/support-feedback', json=body or payload(),
                                 headers={'Idempotency-Key': key or str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_feedback_company_scope_roles_and_optimistic_handling(setup):
    _, sessions, users, clients = setup
    employee, peer, admin, outsider = [clients[key] for key in ('employee', 'peer', 'admin', 'outsider')]
    item = await submit(employee)
    peer_item = await submit(peer)
    admin_item = await submit(admin)
    foreign = await submit(outsider)
    identifier = item['id']
    path = '/api/v1/support-feedback/' + identifier
    assert item['state'] == 'pending' and item['revision'] == 1 and item['handlingNote'] == ''
    assert item['ownerId'] == users['employee'].id
    assert item['ownerName'] == users['employee'].name
    assert (await peer.get(path)).status_code == 404
    assert (await outsider.get(path)).status_code == 404
    assert (await admin.get('/api/v1/support-feedback/' + foreign['id'])).status_code == 404
    update = {'state': 'resolved', 'handlingNote': ' 已修复，请刷新后重试 ', 'expectedRevision': 1}
    assert (await employee.patch(path, json=update)).status_code == 403
    assert (await admin.patch('/api/v1/support-feedback/' + foreign['id'], json=update)).status_code == 404
    changed = await admin.patch(path, json=update)
    assert changed.status_code == 200, changed.text
    assert changed.json()['revision'] == 2
    assert changed.json()['handlingNote'] == '已修复，请刷新后重试'
    stale = await admin.patch(path, json=update)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'revision_conflict'
    assert (await employee.get(path)).json()['state'] == 'resolved'
    for scope in ('mine', 'all'):
        page = (await employee.get('/api/v1/support-feedback', params={'scope': scope})).json()
        assert [row['id'] for row in page['items']] == [identifier]
    admin_page = (await admin.get('/api/v1/support-feedback')).json()
    assert {row['id'] for row in admin_page['items']} == {identifier, peer_item['id'], admin_item['id']}
    own = (await admin.get('/api/v1/support-feedback?scope=mine')).json()
    assert [row['id'] for row in own['items']] == [admin_item['id']]
    # A different company's administrator has no additional access.
    async with sessions.begin() as db:
        other_admin = await db.get(Member, users['outsider'].id)
        other_admin.role = 'admin'
    assert (await outsider.get(path)).status_code == 404
    assert (await outsider.patch(path, json={**update, 'expectedRevision': 2})).status_code == 404


@pytest.mark.asyncio
async def test_feedback_idempotency_concurrency_rate_limit_and_reset(setup):
    _, sessions, users, clients = setup
    employee, peer = clients['employee'], clients['peer']
    body, key = payload(), str(uuid4())
    first, repeat = await asyncio.gather(submit(employee, body, key), submit(employee, body, key))
    assert first == repeat
    assert (await submit(peer, body, key))['id'] != first['id']
    conflict = await employee.post('/api/v1/support-feedback', json={**body, 'description': 'changed'}, headers={'Idempotency-Key': key})
    assert conflict.status_code == 409
    for number in range(4):
        await submit(employee, payload(str(number)))
    limited = await employee.post('/api/v1/support-feedback', json=payload(), headers={'Idempotency-Key': str(uuid4())})
    assert limited.status_code == 429
    assert 1 <= int(limited.headers['Retry-After']) <= 600
    assert limited.json()['error']['retryAfter'] == int(limited.headers['Retry-After'])
    assert await submit(employee, body, key) == first
    async with sessions.begin() as db:
        assert await db.scalar(select(func.count()).select_from(SupportFeedback).where(SupportFeedback.owner_id == users['employee'].id)) == 5
        rows = (await db.scalars(select(SupportFeedback).where(SupportFeedback.owner_id == users['employee'].id))).all()
        for row in rows:
            row.created_at = now() - timedelta(minutes=11)
    await submit(employee)


@pytest.mark.asyncio
async def test_feedback_pagination_state_and_request_boundaries(setup):
    _, _, _, clients = setup
    employee, admin = clients['employee'], clients['admin']
    items = [await submit(employee, payload(str(index))) for index in range(3)]
    patched = await admin.patch('/api/v1/support-feedback/' + items[1]['id'], json={
        'state': 'resolved', 'handlingNote': '', 'expectedRevision': 1,
    })
    assert patched.status_code == 200
    page = (await admin.get('/api/v1/support-feedback?limit=1&state=pending')).json()
    second = (await admin.get('/api/v1/support-feedback', params={'limit': 1, 'state': 'pending', 'cursor': page['nextCursor']})).json()
    assert len(page['items']) == len(second['items']) == 1
    assert page['items'][0]['id'] != second['items'][0]['id']
    assert second['nextCursor'] is None
    resolved = (await employee.get('/api/v1/support-feedback?state=resolved')).json()
    assert [row['id'] for row in resolved['items']] == [items[1]['id']]
    for query in ('limit=21', 'limit=0', 'cursor=-1', 'cursor=1000001', 'state=deleted', 'scope=other'):
        assert (await employee.get('/api/v1/support-feedback?' + query)).status_code == 422
    assert (await employee.post('/api/v1/support-feedback', json=payload())).status_code == 422
    invalid_key = await employee.post('/api/v1/support-feedback', json=payload(), headers={'Idempotency-Key': 'x' * 101})
    assert invalid_key.status_code == 422
    assert (await employee.post('/api/v1/support-feedback', json=payload(), headers={'Origin': 'https://other.test'})).status_code == 403
    assert (await employee.post('/api/v1/support-feedback', json=payload(), headers={'X-CSRF-Token': 'invalid'})).status_code == 403
    await employee.post('/api/v1/auth/logout')
    assert (await employee.get('/api/v1/support-feedback')).status_code == 401


@pytest.mark.asyncio
async def test_feedback_diagnostics_allowlist_and_bounded_inputs(setup):
    _, _, _, clients = setup
    employee, admin = clients['employee'], clients['admin']
    base = payload()
    invalid = [
        {**base, 'description': ''}, {**base, 'description': '   '},
        {**base, 'description': 'x' * 4001}, {**base, 'ownerId': str(uuid4())},
        {**base, 'companyId': str(uuid4())}, {**base, 'state': 'resolved'},
    ]
    for key, value in [
        ('requestBody', 'private work'), ('cookie', 'secret'), ('url', 'https://host/private'),
        ('page', '/assistant/private-id?key=secret'), ('requestId', 'not-an-id'),
        ('browser', 'private message'), ('os', 'private message'), ('appVersion', 'https://host'),
        ('httpStatus', 600), ('httpStatus', '503'), ('category', 'arbitrary'),
        ('viewport', '0x999'), ('occurredAt', 'not-a-date'),
    ]:
        invalid.append({**base, 'diagnostics': {**base['diagnostics'], key: value}})
    for body in invalid:
        response = await employee.post('/api/v1/support-feedback', json=body, headers={'Idempotency-Key': str(uuid4())})
        assert response.status_code == 422, response.text
        assert response.json()['error']['code'] == 'validation_error'
    item = await submit(employee, {'description': '  操作建议  ', 'diagnostics': {'requestId': None, 'browser': None}})
    assert item['description'] == '操作建议' and item['diagnostics'] == {}
    overlong_note = await admin.patch('/api/v1/support-feedback/' + item['id'], json={
        'state': 'resolved', 'handlingNote': 'x' * 2001, 'expectedRevision': 1,
    })
    assert overlong_note.status_code == 422


@pytest.mark.asyncio
async def test_request_logs_use_only_safe_correlated_metadata(setup, caplog):
    settings, _, _, clients = setup
    caplog.set_level(logging.INFO, logger='uvicorn.error.paa_requests')
    client = clients['employee']
    caplog.clear()
    item = await submit(client, payload('PRIVATE_DESCRIPTION_DO_NOT_LOG'))
    response = await client.get('/api/v1/support-feedback/' + item['id'] + '?key=SECRET_QUERY')
    records = [json.loads(record.getMessage().removeprefix('request ')) for record in caplog.records if record.name == 'uvicorn.error.paa_requests']
    read = records[-1]
    assert read['requestId'] == response.headers['X-Request-ID']
    assert read['route'] == '/api/v1/support-feedback/{identifier}'
    assert read['status'] == 200 and read['durationMs'] >= 0 and read['exceptionType'] is None
    assert set(read) == {'requestId', 'route', 'status', 'durationMs', 'exceptionType'}
    safe_output = json.dumps(records)
    for secret in ('PRIVATE_DESCRIPTION_DO_NOT_LOG', 'SECRET_QUERY', item['id'], client.headers['X-CSRF-Token']):
        assert secret not in safe_output
    invalid = await client.post('/api/v1/support-feedback?key=SECRET_QUERY', json={'description': 'SECRET_VALIDATION'}, headers={'Origin': 'https://untrusted.test'})
    assert invalid.status_code == 403
    assert invalid.json()['error']['requestId'] == invalid.headers['X-Request-ID']
    origin = json.loads(caplog.records[-1].getMessage().removeprefix('request '))
    assert origin['status'] == 403 and origin['route'] == '<unmatched>'
    assert origin['requestId'] == invalid.headers['X-Request-ID']
    # These controlled failures are local-only routes on a temporary test app.
    app = create_app(settings)
    @app.get('/test-failure/{identifier}')
    async def fail(identifier: str):
        raise RuntimeError('SECRET_EXCEPTION')
    @app.get('/test-database')
    async def database_failure():
        raise SQLAlchemyError('SECRET_DATABASE')
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as test:
            for path, status, exception in (('/test-failure/PRIVATE_ID?token=SECRET_QUERY', 500, 'RuntimeError'), ('/test-database', 503, 'SQLAlchemyError')):
                failure = await test.get(path)
                assert failure.status_code == status
                entry = json.loads(caplog.records[-1].getMessage().removeprefix('request '))
                assert entry['exceptionType'] == exception
                assert entry['requestId'] == failure.json()['error']['requestId']
                assert entry['requestId'] == failure.headers['X-Request-ID']
                assert all(secret not in failure.text + json.dumps(entry) for secret in ('SECRET_EXCEPTION', 'SECRET_DATABASE', 'SECRET_QUERY', 'PRIVATE_ID'))
    assert logging.getLogger('uvicorn.access').disabled is True


@pytest.mark.asyncio
async def test_request_logs_cover_stream_completion_failure_and_disconnect(setup, caplog):
    settings, _, _, _ = setup
    caplog.set_level(logging.INFO, logger='uvicorn.error.paa_requests')
    app = create_app(settings)
    closed = set()

    @app.get('/test-stream/{mode}')
    async def stream(mode: str):
        async def chunks():
            try:
                yield b'data: PRIVATE_STREAM_BODY\n\n'
                if mode in ('disconnect', 'cancel'):
                    await asyncio.Event().wait()
                await asyncio.sleep(0.03)
                if mode == 'failure':
                    raise RuntimeError('SECRET_LATE_EXCEPTION')
                yield b'data: done\n\n'
            finally:
                closed.add(mode)
        return StreamingResponse(chunks(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store, no-transform'})

    async with app.router.lifespan_context(app):
        for mode in ('complete', 'failure', 'disconnect', 'cancel'):
            caplog.clear()
            incoming, first_body, sent = asyncio.Queue(), asyncio.Event(), []
            incoming.put_nowait({'type': 'http.request', 'body': b'', 'more_body': False})

            async def send(message):
                sent.append(message)
                if message['type'] == 'http.response.body' and message.get('body'):
                    first_body.set()

            scope = {
                'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
                'http_version': '1.1', 'method': 'GET', 'scheme': 'http',
                'path': '/test-stream/' + mode, 'query_string': b'token=SECRET_QUERY',
                'root_path': '', 'headers': [], 'client': ('127.0.0.1', 12345),
                'server': ('test', 80),
            }
            task = asyncio.create_task(app(scope, incoming.get, send))
            try:
                await asyncio.wait_for(first_body.wait(), timeout=2)
                # Logging cannot finish at response.start while the iterator is live.
                assert not [r for r in caplog.records if r.name == 'uvicorn.error.paa_requests']
                if mode == 'disconnect':
                    incoming.put_nowait({'type': 'http.disconnect'})
                if mode == 'cancel':
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    # In particular, no private late exception reaches the ASGI server.
                    await asyncio.wait_for(task, timeout=2)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            assert mode in closed
            starts = [message for message in sent if message['type'] == 'http.response.start']
            assert len(starts) == 1 and starts[0]['status'] == 200
            headers = dict(starts[0]['headers'])
            assert headers[b'cache-control'] == b'no-store, no-transform'
            bodies = [message for message in sent if message['type'] == 'http.response.body']
            assert any(not message.get('more_body', False) for message in bodies) is (mode == 'complete')
            records = [r for r in caplog.records if r.name == 'uvicorn.error.paa_requests']
            assert len(records) == 1
            entry = json.loads(records[0].getMessage().removeprefix('request '))
            assert entry['requestId'] == headers[b'x-request-id'].decode()
            assert entry['route'] == '/test-stream/{mode}' and entry['status'] == 200
            assert entry['exceptionType'] == {'failure': 'RuntimeError', 'cancel': 'CancelledError'}.get(mode)
            if mode in ('complete', 'failure'):
                assert entry['durationMs'] >= 25
            assert all(record.exc_info is None for record in caplog.records)
            assert all(secret not in caplog.text for secret in ('PRIVATE_STREAM_BODY', 'SECRET_LATE_EXCEPTION', 'SECRET_QUERY'))
