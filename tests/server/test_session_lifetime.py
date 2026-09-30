"""Session policy through real ASGI responses and committed PostgreSQL rows."""
from dataclasses import replace
from datetime import timedelta
from http.cookies import SimpleCookie
import re

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.db.base import now
from app.http.dependencies import AUTH, DB
from app.http.session_renewal import BACKGROUND_READS, SessionRenewal
from app.modules.auth.models import Session
from app.modules.auth.session_policy import ABSOLUTE_LIFETIME, IDLE_LIFETIME
from app.modules.auth.sessions import COOKIE, digest
from app.modules.conversations.models import Conversation
from app.tasks.models import Job
from test_company import send

pytestmark = pytest.mark.asyncio


def freeze(monkeypatch, instant):
    for module in ('app.modules.auth.sessions', 'app.http.session_renewal',
                   'app.http.dependencies', 'app.modules.auth.desktop_router',
                   'app.tasks.feedback.feedback'):
        monkeypatch.setattr(module + '.now', lambda: instant)


async def stored(sessions, client):
    async with sessions() as db:
        return await db.scalar(select(Session).where(Session.token_hash == digest(client.cookies.get(COOKIE))))


async def age_session(sessions, client, created_at, expires_at):
    async with sessions.begin() as db:
        record = await db.scalar(select(Session).where(Session.token_hash == digest(client.cookies.get(COOKIE))))
        record.created_at, record.expires_at = created_at, expires_at
        return record


def cookie(response):
    result = SimpleCookie()
    for header in response.headers.get_list('set-cookie'):
        result.load(header)
    return result.get(COOKIE)


async def test_password_login_seven_days_persistent_cookie_and_original_timestamp(setup, monkeypatch):
    settings, sessions, users, clients = setup
    instant = now()
    freeze(monkeypatch, instant)
    client = clients['employee']
    response = await client.post('/api/v1/auth/login', json={
        'username': users['employee'].username, 'password': 'controlled-test-password',
    })
    record = await stored(sessions, client)
    assert response.status_code == 200
    assert record.created_at == instant and record.expires_at == instant + IDLE_LIFETIME
    value = cookie(response)
    assert int(value['max-age']) == 7 * 86400
    assert value['httponly'] and value['samesite'] == 'lax' and value['path'] == '/'
    # A new browser client can reuse the persistent cookie without logging in.
    async with httpx.AsyncClient(transport=client._transport, base_url='http://test', cookies=client.cookies) as reopened:
        identity = await reopened.get('/api/v1/auth/me')
        assert identity.status_code == 200 and identity.json()['csrf'] == record.csrf
    client._transport.app.state.settings = replace(settings, cookie_secure=True)
    secure = await client.post('/api/v1/auth/login', json={
        'username': users['employee'].username, 'password': 'controlled-test-password',
    })
    assert cookie(secure)['secure']


async def test_throttle_skips_cookie_and_transaction_until_30_minutes(setup, monkeypatch):
    _, sessions, _, clients = setup
    client = clients['employee']
    original = await stored(sessions, client)
    token, csrf = client.cookies.get(COOKIE), original.csrf
    engine = client._transport.app.state.sessions.kw['bind'].sync_engine
    writes, transactions = [], []

    def statement(conn, cursor, sql, parameters, context, executemany):
        if sql.startswith('UPDATE company_session'):
            writes.append(sql)

    def begin(conn):
        transactions.append(conn)

    event.listen(engine, 'before_cursor_execute', statement)
    event.listen(engine, 'begin', begin)
    try:
        freeze(monkeypatch, original.created_at + timedelta(minutes=29, seconds=59))
        response = await client.get('/api/v1/auth/me')
        assert response.status_code == 200 and not writes and len(transactions) == 1
        assert cookie(response) is None
        transactions.clear()
        freeze(monkeypatch, original.created_at + timedelta(minutes=30))
        response = await client.get('/api/v1/auth/me')
        assert response.status_code == 200 and len(writes) == 1 and len(transactions) == 2
        assert int(cookie(response)['max-age']) == 7 * 86400
        # Further requests use the same token without reasserting its cookie.
        transactions.clear()
        freeze(monkeypatch, original.created_at + timedelta(minutes=31))
        response = await client.get('/api/v1/auth/me', headers={'Cookie': COOKIE + '=' + token})
        assert response.status_code == 200 and len(writes) == 1 and len(transactions) == 1
        assert cookie(response) is None
    finally:
        event.remove(engine, 'before_cursor_execute', statement)
        event.remove(engine, 'begin', begin)
    record = await stored(sessions, client)
    assert record.created_at == original.created_at and record.csrf == csrf
    assert record.id == original.id and client.cookies.get(COOKIE) == token
    assert record.expires_at == original.created_at + timedelta(minutes=30) + IDLE_LIFETIME


@pytest.mark.parametrize('age,remaining,expected', [
    (timedelta(days=4), timedelta(hours=4), IDLE_LIFETIME),
    (timedelta(days=29), timedelta(hours=20), timedelta(days=1)),
    # Final cap fill is allowed with less than 30 minutes of advancement.
    (timedelta(days=23, minutes=5), IDLE_LIFETIME - timedelta(minutes=15), IDLE_LIFETIME - timedelta(minutes=5)),
])
async def test_legacy_upgrade_and_absolute_cap(setup, monkeypatch, age, remaining, expected):
    _, sessions, _, clients = setup
    instant = now()
    client = clients['employee']
    original = await age_session(sessions, client, instant - age, instant + remaining)
    freeze(monkeypatch, instant)
    response = await client.get('/api/v1/work-items')
    assert response.status_code == 200
    record = await stored(sessions, client)
    assert record.created_at == original.created_at and record.expires_at == instant + expected
    assert int(cookie(response)['max-age']) == int(expected.total_seconds())
    assert record.expires_at <= record.created_at + ABSOLUTE_LIFETIME


@pytest.mark.parametrize('created,expires', [
    (timedelta(days=-7), timedelta(0)),
    (timedelta(hours=-8), timedelta(seconds=-1)),
    (timedelta(days=-30), timedelta(days=1)),
])
async def test_idle_expired_old_expired_and_absolute_expired_cannot_revive(setup, monkeypatch, created, expires):
    _, sessions, _, clients = setup
    instant = now()
    client = clients['employee']
    original = await age_session(sessions, client, instant + created, instant + expires)
    freeze(monkeypatch, instant)
    response = await client.get('/api/v1/auth/me')
    assert response.status_code == 401 and cookie(response) is None
    assert (await stored(sessions, client)).expires_at == original.expires_at


async def test_successful_writes_only_renew_current_session_and_commit_first(setup, monkeypatch):
    _, sessions, users, clients = setup
    instant = now()
    client = clients['employee']
    original = await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(hours=6))
    async with sessions.begin() as db:
        other = Session(member_id=users['employee'].id, token_hash=digest('other-controlled-token'), csrf='other-csrf', created_at=original.created_at, expires_at=original.expires_at)
        db.add(other)
        await db.flush()
        other_id = other.id
    freeze(monkeypatch, instant)
    response = await client.post('/api/v1/conversations', json={'title': '续期事务检查'})
    assert response.status_code == 201 and cookie(response) is not None
    async with sessions() as db:
        assert await db.get(Conversation, response.json()['id'])
        assert (await db.get(Session, other_id)).expires_at == original.expires_at
    assert (await stored(sessions, client)).expires_at == instant + IDLE_LIFETIME


async def test_errors_anonymous_csrf_origin_and_server_failure_do_not_renew(setup, monkeypatch):
    _, sessions, _, clients = setup
    instant = now()
    client = clients['employee']
    original = await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(hours=6))
    freeze(monkeypatch, instant)
    app = client._transport.app

    @app.get('/api/v1/test-session-failure')
    async def fail(actor=AUTH, db=DB):
        raise RuntimeError('controlled failure')

    responses = [
        await client.get('/api/v1/members'),
        await client.get('/api/v1/conversations/missing'),
        await client.post('/api/v1/conversations', json={'title': ['not-a-string']}),
        await client.post('/api/v1/conversations', json={'title': 'blocked'}, headers={'X-CSRF-Token': 'wrong'}),
        await client.post('/api/v1/conversations', json={'title': 'blocked'}, headers={'Origin': 'http://foreign'}),
        await client.get('/api/v1/test-session-failure'),
        await client.get('/api/v1/auth/me', headers={'Cookie': ''}),
    ]
    assert [response.status_code for response in responses] == [403, 404, 422, 403, 403, 500, 401]
    assert all(cookie(response) is None for response in responses)
    assert (await stored(sessions, client)).expires_at == original.expires_at


async def test_long_response_past_expiry_does_not_renew(setup, monkeypatch):
    _, sessions, _, clients = setup
    instant = now()
    client = clients['employee']
    original = await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(seconds=1))
    freeze(monkeypatch, instant)

    @client._transport.app.get('/api/v1/test-long-session')
    async def delayed(actor=AUTH, db=DB):
        freeze(monkeypatch, instant + timedelta(seconds=1))
        return {'ok': True}

    response = await client.get('/api/v1/test-long-session')
    assert response.status_code == 200 and cookie(response) is None
    assert (await stored(sessions, client)).expires_at == original.expires_at


@pytest.mark.parametrize('phase', ['business_commit', 'renewal_commit'])
async def test_commit_failures_never_send_unpersisted_cookie_or_lose_success(setup, monkeypatch, phase):
    _, sessions, users, clients = setup
    instant = now()
    client = clients['employee']
    original = await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(hours=6))
    freeze(monkeypatch, instant)
    engine = client._transport.app.state.sessions.kw['bind'].sync_engine
    transactions = {}
    observed = []

    def statement(conn, cursor, sql, parameters, context, executemany):
        if sql.startswith('INSERT INTO company_conversation'):
            transactions[conn] = 'business_commit'
        if sql.startswith('UPDATE company_session'):
            transactions[conn] = 'renewal_commit'

    def commit(conn):
        kind = transactions.pop(conn, None)
        if kind:
            observed.append(kind)
        if kind == phase:
            raise OperationalError('controlled commit failure', {}, Exception('unavailable'))

    event.listen(engine, 'before_cursor_execute', statement)
    event.listen(engine, 'commit', commit)
    try:
        response = await client.post('/api/v1/conversations', json={'title': '事务故障边界'})
    finally:
        event.remove(engine, 'before_cursor_execute', statement)
        event.remove(engine, 'commit', commit)
    assert response.status_code == (503 if phase == 'business_commit' else 201)
    assert cookie(response) is None
    assert observed == (['business_commit'] if phase == 'business_commit' else ['business_commit', 'renewal_commit'])
    async with sessions() as db:
        items = (await db.scalars(select(Conversation).where(Conversation.owner_id == users['employee'].id))).all()
        assert len(items) == (0 if phase == 'business_commit' else 1)
    assert (await stored(sessions, client)).expires_at == original.expires_at


async def test_all_background_routes_are_excluded_and_feedback_does_not_keep_session_alive(setup, monkeypatch):
    _, sessions, _, clients = setup
    client = clients['employee']
    result = await send(client)
    async with sessions.begin() as db:
        (await db.get(Job, result['jobId'])).state = 'awaiting_retry'
    instant = now()
    original = await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(seconds=1))
    freeze(monkeypatch, instant)
    # Exercise the real recovery and SSE routes with authentic PostgreSQL data.
    for suffix in ('', '/feedback', '/events'):
        response = await client.get('/api/v1/jobs/' + result['jobId'] + suffix)
        assert response.status_code == 200 and cookie(response) is None
    # Check each template through real FastAPI routing and authentication without
    # building unrelated report/voiceprint business data. The main app includes
    # lazy routers, so inspecting only its top-level app.routes misses them.
    app = FastAPI()
    app.state.settings = client._transport.app.state.settings
    app.state.sessions = client._transport.app.state.sessions
    app.add_middleware(SessionRenewal)

    async def background(actor=AUTH):
        return {'ok': True}

    for path in BACKGROUND_READS:
        app.add_api_route(path, background, methods=['GET'])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', cookies=client.cookies) as polling:
        for path in BACKGROUND_READS:
            response = await polling.get(re.sub(r'\{[^}]+\}', 'controlled-id', path))
            assert response.status_code == 200 and cookie(response) is None, path
    assert (await stored(sessions, client)).expires_at == original.expires_at
    freeze(monkeypatch, original.expires_at)
    assert (await client.get('/api/v1/jobs/' + result['jobId'] + '/feedback')).status_code == 401
    assert (await client.get('/api/v1/auth/me')).status_code == 401
