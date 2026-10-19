"""Feedback recovery uses short authorized transactions, without nested pool borrows."""
import asyncio
import hashlib
import json

import httpx
import pytest
from sqlalchemy import delete, event, text
from starlette.responses import StreamingResponse

from app.modules.auth.models import Session
from app.tasks.feedback import feedback
from app.tasks.models import Job
from _support.http.company import send

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('endpoint', ['feedback', 'events'])
async def test_concurrent_feedback_does_not_hold_auth_connections(setup, monkeypatch, endpoint):
    _, sessions, _, clients = setup
    client = clients['employee']
    sent = await send(client)
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state = 'awaiting_retry'
    original = feedback.snapshot
    barrier = asyncio.Event()
    entered = 0

    async def simultaneous(*args, **kwargs):
        nonlocal entered
        entered += 1
        if entered <= 3:
            if entered == 3:
                barrier.set()
            await barrier.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(feedback, 'snapshot', simultaneous)
    # The application pool has only three connections. Holding AUTH's connection
    # before snapshot would make all three requests wait for a fourth connection.
    responses = await asyncio.wait_for(asyncio.gather(*[
        client.get(f"/api/v1/jobs/{sent['jobId']}/{endpoint}") for _ in range(3)
    ]), timeout=5)
    assert all(response.status_code == 200 for response in responses)
    for response in responses:
        if endpoint == 'events':
            assert '"state": "awaiting_retry"' in response.text
        else:
            assert response.json()['state'] == 'awaiting_retry'
    engine = client._transport.app.state.sessions.kw['bind']
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize('endpoint', ['feedback', 'events'])
async def test_feedback_authentication_still_checks_owner_company_and_session(setup, endpoint):
    _, sessions, _, clients = setup
    client = clients['employee']
    sent = await send(client)
    path = f"/api/v1/jobs/{sent['jobId']}/{endpoint}"
    for role in ('peer', 'outsider'):
        assert (await clients[role].get(path)).status_code == 404
    async with httpx.AsyncClient(transport=client._transport, base_url='http://test') as anonymous:
        assert (await anonymous.get(path)).status_code == 401
    if endpoint == 'events':
        assert (await client.get(path, headers={'Origin': 'http://foreign'})).status_code == 403
    token = hashlib.sha256(client.cookies.get('paa_company_session').encode()).hexdigest()
    async with sessions.begin() as db:
        await db.execute(delete(Session).where(Session.token_hash == token))
    assert (await client.get(path)).status_code == 401


async def test_stream_remains_open_past_the_old_one_minute_limit(monkeypatch):
    samples = 0
    async def snapshot(*_):
        nonlocal samples
        samples += 1
        return {
            'attempt': 1, 'fence': 1, 'seq': samples,
            'state': 'succeeded' if samples == 125 else 'running',
            'updatedAt': '2026-09-29T01:00:00Z',
            'actions': [], 'taskOutcome': None, 'interactions': [],
        }
    async def sleep(_):
        pass
    monkeypatch.setattr(feedback, 'snapshot', snapshot)
    monkeypatch.setattr(feedback.asyncio, 'sleep', sleep)
    received = [json.loads(item.split('data: ', 1)[1]) async for item in feedback.events(None, '', 'job')]
    assert len(received) == 125
    assert received[-1]['state'] == 'succeeded'


async def test_sse_disconnect_during_pool_ping_finishes_snapshot_and_releases_connection(setup, monkeypatch):
    _, sessions, _, clients = setup
    sent = await send(clients['employee'])
    token = hashlib.sha256(clients['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    engine = sessions.kw['bind']
    # Warm an existing connection, then hold only the real PostgreSQL pool ping
    # long enough to deterministically disconnect while that command is ACTIVE.
    async with sessions.begin() as db:
        await db.scalar(text('SELECT 1'))
    monkeypatch.setattr(engine.sync_engine.dialect, '_dialect_specific_select_one', 'SELECT pg_sleep(0.05)')
    original_ping = engine.sync_engine.dialect.do_ping
    entered = asyncio.Event()
    errors = []

    def ping(connection):
        entered.set()
        return original_ping(connection)

    def observe(ctx):
        errors.append(type(ctx.original_exception).__name__)

    monkeypatch.setattr(engine.sync_engine.dialect, 'do_ping', ping)
    event.listen(engine.sync_engine, 'handle_error', observe)
    received = []

    async def receive():
        await entered.wait()
        await asyncio.sleep(.005)
        return {'type': 'http.disconnect'}

    async def send_frame(value):
        received.append(value)

    try:
        await asyncio.wait_for(StreamingResponse(feedback.events(sessions, token, sent['jobId']))(
            {'type': 'http', 'asgi': {'spec_version': '2.3'}}, receive, send_frame), timeout=2)
        assert errors == []
        assert engine.pool.checkedout() == 0
        assert not any(item.get('body') for item in received)
        # Disconnect must not cancel the user's background task or poison reuse.
        async with sessions.begin() as db:
            assert (await db.get(Job, sent['jobId'])).state == 'queued'
    finally:
        event.remove(engine.sync_engine, 'handle_error', observe)


async def test_sse_snapshot_timeout_still_bounds_slow_queries_and_releases_pool(setup, monkeypatch):
    _, sessions, _, _ = setup
    engine = sessions.kw['bind']

    async def slow(*args, **kwargs):
        async with sessions.begin() as db:
            await db.execute(text('SELECT pg_sleep(1)'))

    monkeypatch.setattr(feedback, 'snapshot', slow)
    monkeypatch.setattr(feedback, 'SSE_SNAPSHOT_TIMEOUT', .05)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(feedback.stream_snapshot(sessions, '', ''), timeout=2)
    assert engine.pool.checkedout() == 0
    async with sessions.begin() as db:
        assert await db.scalar(text('SELECT 1')) == 1
