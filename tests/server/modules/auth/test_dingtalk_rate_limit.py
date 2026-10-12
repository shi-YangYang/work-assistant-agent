"""Shared office login bursts and adversarial retries, with real PostgreSQL."""
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from _support.http.dingtalk import app_for, begin, complete, enable, logged_in
from app.db.base import now
from app.modules.auth.dingtalk import rate_limit
from app.modules.auth.models import DingTalkAuthorization, DingTalkIdentity, LoginAttempt
from app.modules.auth.sessions import digest

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def browsers(setup, monkeypatch):
    await enable(setup, monkeypatch)
    settings, sessions, _, clients = setup
    owned_keys = set()
    async with AsyncExitStack() as stack:
        async def make(host, *, app=None, headers=None):
            owned_keys.add(digest('dingtalk:login:ip:' + host))
            async def record(response):
                token = response.cookies.get(rate_limit.RATE_COOKIE)
                if token:
                    owned_keys.add(digest('dingtalk:login:browser:' + token))
            return await stack.enter_async_context(httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app or app_for(clients), client=(host, 1234)),
                base_url='http://test', headers={'Origin': 'http://test', **(headers or {})},
                event_hooks={'response': [record]},
            ))
        yield make, owned_keys
    async with sessions.begin() as db:
        await db.execute(delete(LoginAttempt).where(LoginAttempt.identity.in_(owned_keys)))


@pytest.mark.parametrize('count', [50, 100])
async def test_office_burst_logs_in_distinct_members_without_crossing_sessions(setup, browsers, count):
    _, sessions, users, _ = setup
    make, _ = browsers
    host = uuid4().hex
    clients = [await make(host) for _ in range(count)]

    async def login(index, client):
        state = await begin(client)
        code = 'member-' + uuid4().hex
        result = await complete(client, state, code)
        assert result.headers['location'].endswith('dingtalk=logged-in')
        identity = await logged_in(client)
        assert identity['member']['role'] == 'employee'
        assert (await client.get('/api/v1/work-items')).status_code == 200
        return state, code, identity['member']['id']

    results = await asyncio.wait_for(asyncio.gather(*(login(i, c) for i, c in enumerate(clients))), 20)
    assert len({row[2] for row in results}) == count
    async with sessions() as db:
        links = (await db.scalars(select(DingTalkIdentity).where(DingTalkIdentity.company_id == users['admin'].company_id))).all()
        assert {(link.union_id, link.member_id) for link in links} == {(code, member) for _, code, member in results}
    replay = await complete(clients[0], results[0][0], results[0][1])
    assert 'reason=expired' in replay.headers['location']


async def test_browser_retries_are_bounded_atomically_without_blocking_colleague(setup, browsers):
    _, sessions, _, _ = setup
    make, _ = browsers
    host = uuid4().hex
    client, colleague = await make(host), await make(host)
    await begin(client)
    token = client.cookies.get(rate_limit.RATE_COOKIE)
    responses = await asyncio.gather(*(client.post('/api/v1/auth/dingtalk/start') for _ in range(20)))
    assert sum(r.status_code == 200 for r in responses) == 11
    rejected = [r for r in responses if r.status_code == 429]
    assert len(rejected) == 9
    assert all(r.json()['error']['code'] == 'login_browser_rate_limited' for r in rejected)
    assert all(1 <= int(r.headers['Retry-After']) <= 600 for r in rejected)
    assert client.cookies.get(rate_limit.RATE_COOKIE) == token
    await begin(colleague)
    async with sessions() as db:
        # Browser rejections still consume network budget; deletion cannot bypass it.
        assert await db.scalar(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.identity == digest('dingtalk:login:ip:' + host))) == 22


async def test_cookie_rotation_is_still_limited_per_ip_and_other_network_is_independent(setup, browsers):
    make, _ = browsers
    host = uuid4().hex
    clients = [await make(host) for _ in range(125)]
    results = await asyncio.wait_for(asyncio.gather(*(c.post('/api/v1/auth/dingtalk/start') for c in clients)), 15)
    assert sum(r.status_code == 200 for r in results) == 120
    rejected = [r for r in results if r.status_code == 429]
    assert len(rejected) == 5
    assert all(r.json()['error']['code'] == 'login_network_rate_limited' for r in rejected)
    assert all(1 <= int(r.headers['Retry-After']) <= 60 for r in rejected)
    another = await make(uuid4().hex)
    await begin(another)


async def test_retry_after_tracks_rolling_window_and_counts_survive_new_app(setup, browsers):
    from app.main import create_app
    settings, sessions, _, _ = setup
    make, _ = browsers
    client = await make(uuid4().hex)
    for _ in range(12):
        await begin(client)
    token = client.cookies.get(rate_limit.RATE_COOKIE)
    key = digest('dingtalk:login:browser:' + token)
    async with sessions.begin() as db:
        await db.execute(update(LoginAttempt).where(LoginAttempt.identity == key).values(created_at=now() - timedelta(seconds=570)))
    app = create_app(settings)
    try:
        restarted = await make(uuid4().hex, app=app)
        restarted.cookies.set(rate_limit.RATE_COOKIE, token, path=rate_limit.COOKIE_PATH)
        response = await restarted.post('/api/v1/auth/dingtalk/start')
        assert response.status_code == 429
        assert 28 <= int(response.headers['Retry-After']) <= 30
        async with sessions.begin() as db:
            await db.execute(update(LoginAttempt).where(LoginAttempt.identity == key).values(created_at=now() - timedelta(seconds=601)))
        # Use the original fixture app's company selection for successful admission.
        await begin(client)
    finally:
        await app.state.sessions.kw['bind'].dispose()


async def test_rate_cookie_is_signed_expiring_and_independent_of_oauth_browser(setup, browsers, monkeypatch):
    settings, sessions, _, _ = setup
    make, _ = browsers
    client = await make(uuid4().hex)
    first = await client.post('/api/v1/auth/dingtalk/start')
    token = client.cookies.get(rate_limit.RATE_COOKIE)
    cookie_header = next(h for h in first.headers.get_list('set-cookie') if h.startswith(rate_limit.RATE_COOKIE + '='))
    assert 'HttpOnly' in cookie_header and 'SameSite=lax' in cookie_header and 'Max-Age=3600' in cookie_header
    assert rate_limit.browser_token(token, settings) == (token, False)
    for invalid in (token[:-1] + ('1' if token[-1] != '1' else '2'), 'x' * 2000, 'bad'):
        fresh, created = rate_limit.browser_token(invalid, settings)
        assert created and fresh != invalid
    issued = int(token.split('.')[1])
    monkeypatch.setattr(rate_limit, 'time', SimpleNamespace(time=lambda: issued + 3600))
    assert rate_limit.browser_token(token, settings)[1]
    monkeypatch.setattr(rate_limit, 'time', SimpleNamespace(time=lambda: issued - 1))
    assert rate_limit.browser_token(token, settings)[1]
    async with sessions() as db:
        assert not await db.scalar(select(DingTalkAuthorization.id).where(DingTalkAuthorization.browser_hash == digest(token)))


async def test_only_trusted_proxy_can_select_client_budget(setup, browsers):
    _, _, _, clients = setup
    make, keys = browsers
    proxy = '172.30.254.2'
    app = ProxyHeadersMiddleware(app_for(clients), trusted_hosts=[proxy])
    office = uuid4().hex
    keys.add(digest('dingtalk:login:ip:' + office))
    trusted = await make(proxy, app=app, headers={'X-Forwarded-For': office})
    for _ in range(12):
        await begin(trusted)
    # A direct caller cannot pick another IP by forging the forwarding header.
    direct_host = uuid4().hex
    direct = await make(direct_host, app=app)
    for i in range(120):
        direct.cookies.clear()
        result = await direct.post('/api/v1/auth/dingtalk/start', headers={'X-Forwarded-For': '198.51.100.' + str(i + 1)})
        assert result.status_code == 200
    direct.cookies.clear()
    result = await direct.post('/api/v1/auth/dingtalk/start', headers={'X-Forwarded-For': uuid4().hex})
    assert result.status_code == 429
    assert result.json()['error']['code'] == 'login_network_rate_limited'
