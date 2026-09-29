import asyncio
import hashlib

import httpx
import pytest
from sqlalchemy import func, select

from app.modules.auth.models import LoginAttempt
from app.modules.members.models import Member
from app.security.locks import company_lock

pytestmark = pytest.mark.asyncio


async def test_parallel_login_cannot_share_seventh_failure_or_queue_hashes(setup, monkeypatch):
    _, sessions, users, c = setup
    user = users['employee']
    identity = hashlib.sha256(f'127.0.0.1:{user.username}'.encode()).hexdigest()
    async with sessions.begin() as db:
        db.add_all(LoginAttempt(identity=identity) for _ in range(7))
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    async def verify(*args):
        nonlocal count
        count += 1
        entered.set()
        await release.wait()
        return False
    monkeypatch.setattr('app.modules.auth.router.verify_password', verify)
    payload = {'username': user.username, 'password': 'bad-password'}
    first = asyncio.create_task(c['employee'].post('/api/v1/auth/login', json=payload))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        results = await asyncio.gather(*(c['employee'].post('/api/v1/auth/login', json=payload) for _ in range(5)))
        assert [r.status_code for r in results] == [429] * 5
    finally:
        release.set()
    assert (await first).status_code == 401 and count == 1
    assert (await c['employee'].post('/api/v1/auth/login', json=payload)).status_code == 429
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity == identity)) == 8


async def test_login_success_clears_failures_and_disable_during_hash_still_blocks(setup, monkeypatch):
    _, sessions, users, c = setup
    payload = {'username': users['employee'].username, 'password': 'controlled-test-password'}
    identity = hashlib.sha256(f"127.0.0.1:{payload['username']}".encode()).hexdigest()
    async with sessions.begin() as db:
        db.add_all(LoginAttempt(identity=identity) for _ in range(7))
    assert (await c['employee'].post('/api/v1/auth/login', json=payload)).status_code == 200
    async with sessions() as db:
        assert not await db.scalar(select(LoginAttempt.id).where(LoginAttempt.identity == identity))
    async def disable(*args):
        async with sessions.begin() as db:
            await company_lock(db, users['employee'].company_id)
            (await db.get(Member, users['employee'].id)).active = False
        return True
    monkeypatch.setattr('app.modules.auth.router.verify_password', disable)
    assert (await c['employee'].post('/api/v1/auth/login', json=payload)).status_code == 401


async def test_shared_reads_parallel_writer_waits_and_cannot_upgrade(setup):
    _, sessions, users, _ = setup
    company = users['admin'].company_id
    acquired = asyncio.Event()
    async with sessions.begin() as first:
        await company_lock(first, company, shared=True)
        async with sessions.begin() as second:
            await asyncio.wait_for(company_lock(second, company, shared=True), 2)
            with pytest.raises(RuntimeError, match='cannot upgrade'):
                await company_lock(second, company)
        async def writer():
            async with sessions.begin() as db:
                await company_lock(db, company)
                acquired.set()
        task = asyncio.create_task(writer())
        await asyncio.sleep(.05)
        assert not acquired.is_set()
    await asyncio.wait_for(task, 2)
    assert acquired.is_set()


async def test_read_endpoint_rechecks_revocation_after_waiting_for_writer(setup):
    _, sessions, users, c = setup
    from app.modules.auth.sessions import revoke_member
    async with sessions.begin() as db:
        await company_lock(db, users['admin'].company_id)
        request = asyncio.create_task(c['admin'].get('/api/v1/settings/model-usage'))
        await asyncio.sleep(.05)
        assert not request.done()
        await revoke_member(db, users['admin'].id)
    assert (await asyncio.wait_for(request, 2)).status_code == 401


async def test_nested_rollback_does_not_cache_released_write_lock(setup):
    _, sessions, users, _ = setup
    company = users['admin'].company_id
    async with sessions.begin() as first:
        nested = await first.begin_nested()
        await company_lock(first, company)
        await nested.rollback()
        async with sessions.begin() as second:
            await company_lock(second, company)
            reacquired = asyncio.create_task(company_lock(first, company))
            await asyncio.sleep(.05)
            assert not reacquired.done()
        await asyncio.wait_for(reacquired, 2)


async def test_parallel_renewals_advance_once_release_business_pool_and_share_deadline(setup, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import event
    from app.db.base import now
    from app.modules.auth import sessions as auth_sessions
    from test_session_lifetime import age_session, cookie, freeze, stored

    _, sessions, _, clients = setup
    instant = now()
    client = clients['employee']
    await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(hours=6))
    freeze(monkeypatch, instant)
    barrier = asyncio.Event()
    entered = 0
    original = auth_sessions.renew_session
    engine = client._transport.app.state.sessions.kw['bind']
    updates = []

    async def renew(*args):
        nonlocal entered
        entered += 1
        if entered == 3:
            # All AUTH dependencies must already have released their connections.
            assert engine.pool.checkedout() == 0
            barrier.set()
        await barrier.wait()
        return await original(*args)

    def statement(conn, cursor, sql, parameters, context, executemany):
        if sql.startswith('UPDATE company_session'):
            updates.append(sql)

    monkeypatch.setattr('app.http.session_renewal.renew_session', renew)
    event.listen(engine.sync_engine, 'before_cursor_execute', statement)
    try:
        responses = await asyncio.wait_for(asyncio.gather(*[
            client.get('/api/v1/auth/me') for _ in range(3)
        ]), 5)
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', statement)
    assert all(response.status_code == 200 for response in responses)
    assert len(updates) == 1
    assert {cookie(response)['max-age'] for response in responses} == {'604800'}
    assert (await stored(sessions, client)).expires_at == instant + timedelta(days=7)
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize('change', ['logout', 'password', 'reset_password', 'disable', 'permission'])
async def test_revocation_committed_between_business_and_renewal_cannot_resurrect(setup, monkeypatch, change):
    from datetime import timedelta
    from app.db.base import now
    from app.modules.auth.models import Session
    from app.modules.auth import sessions as auth_sessions
    from test_session_lifetime import age_session, cookie, freeze

    _, sessions, users, clients = setup
    instant = now()
    client = clients['employee']
    original_token = client.cookies.get('paa_company_session')
    original = await age_session(sessions, client, instant - timedelta(hours=2), instant + timedelta(hours=6))
    freeze(monkeypatch, instant)
    entered, release = asyncio.Event(), asyncio.Event()
    original_lock = auth_sessions.company_lock

    async def lock(db, company_id):
        entered.set()
        await release.wait()
        await original_lock(db, company_id)

    monkeypatch.setattr(auth_sessions, 'company_lock', lock)
    pending = asyncio.create_task(client.get('/api/v1/auth/me'))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        if change == 'logout':
            revoked = await client.post('/api/v1/auth/logout')
        elif change == 'password':
            revoked = await client.post('/api/v1/auth/password', json={
                'currentPassword': 'controlled-test-password', 'newPassword': 'changed-controlled-password',
            })
        elif change == 'reset_password':
            revoked = await clients['admin'].post('/api/v1/members/' + users['employee'].id + '/reset-password', json={'password': 'reset-controlled-password'})
        elif change == 'disable':
            revoked = await clients['admin'].patch('/api/v1/members/' + users['employee'].id, json={'active': False})
        else:
            async with sessions.begin() as db:
                await original_lock(db, users['employee'].company_id)
                (await db.get(Member, users['employee'].id)).role = 'admin'
                await auth_sessions.revoke_member(db, users['employee'].id)
            revoked = None
        assert revoked is None or revoked.status_code == 200
        if change in ('logout', 'password'):
            assert cookie(revoked)['max-age'] == '0'
    finally:
        release.set()
    response = await asyncio.wait_for(pending, 3)
    assert response.status_code == 200 and cookie(response) is None
    async with sessions() as db:
        assert await db.get(Session, original.id) is None
    old = await client.get('/api/v1/auth/me', headers={'Cookie': 'paa_company_session=' + original_token})
    assert old.status_code == 401


@pytest.mark.parametrize('change', ['logout', 'account_switch'])
async def test_throttled_delayed_response_preserves_logout_and_new_account_cookie(setup, monkeypatch, change):
    from datetime import timedelta
    from app.modules.auth.models import Session
    from app.modules.auth.sessions import COOKIE
    from test_session_lifetime import cookie, freeze, stored

    _, sessions, users, clients = setup
    client = clients['admin']
    original = await stored(sessions, client)
    original_token = client.cookies.get(COOKIE)
    freeze(monkeypatch, original.created_at + timedelta(minutes=10))
    entered, release = asyncio.Event(), asyncio.Event()

    async def catalog_response(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={'data': []})

    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(catalog_response)))
    # Exercise the production slow route: authentication finishes before the
    # controlled provider responds, while logout and login remain available.
    pending = asyncio.create_task(client.post('/api/v1/settings/model-services/models', json={
        'name': '受控模型目录', 'baseUrl': 'https://example.com/v1',
        'apiKey': 'controlled-key-not-real', 'draftVersion': 'cookie-race',
    }))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        logout = await client.post('/api/v1/auth/logout')
        assert logout.status_code == 200 and cookie(logout)['max-age'] == '0'
        assert client.cookies.get(COOKIE) is None
        current_token = None
        if change == 'account_switch':
            login = await client.post('/api/v1/auth/login', json={
                'username': users['employee'].username, 'password': 'controlled-test-password',
            })
            assert login.status_code == 200
            client.headers['X-CSRF-Token'] = login.json()['csrf']
            current_token = client.cookies.get(COOKIE)
            assert current_token and current_token != original_token
    finally:
        release.set()
        response = await asyncio.wait_for(pending, 3)

    assert response.status_code == 200 and cookie(response) is None
    assert client.cookies.get(COOKIE) == current_token
    identity = await client.get('/api/v1/auth/me')
    if change == 'account_switch':
        assert identity.status_code == 200 and identity.json()['member']['id'] == users['employee'].id
    else:
        assert identity.status_code == 401
    async with sessions() as db:
        assert await db.get(Session, original.id) is None
    old = await client.get('/api/v1/auth/me', headers={'Cookie': COOKIE + '=' + original_token})
    assert old.status_code == 401
