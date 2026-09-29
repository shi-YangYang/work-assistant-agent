"""Feedback recovery uses short authorized transactions, without nested pool borrows."""
import asyncio
import hashlib
import json

import httpx
import pytest
from sqlalchemy import delete

from app.modules.auth.models import Session
from app.tasks import feedback
from app.tasks.models import Job
from test_company import send

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

    async def simultaneous(*args):
        nonlocal entered
        entered += 1
        if entered <= 3:
            if entered == 3:
                barrier.set()
            await barrier.wait()
        return await original(*args)

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
