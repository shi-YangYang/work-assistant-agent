import asyncio
import httpx
import json
import logging
import app.cli as cli
import app.modules.auth.dingtalk.router as routes
import app.modules.auth.router as api_module
import pytest
from dataclasses import replace
from datetime import timedelta
from app.main import create_app
from app.cli import prepare_model_key as cli_prepare_model_key
from app.db.base import now
from app.integrations.dingtalk import DingTalkProvider
from app.modules.auth.dingtalk.service import BROWSER_COOKIE, PROOF_COOKIE, login_company as routes_login_company
from app.modules.auth.models import DingTalkAuthorization, DingTalkConfig, DingTalkIdentity, Session
from app.modules.auth.sessions import COOKIE, digest, verify_password as api_module_verify_password
from app.modules.members.models import Member
from app.modules.reports.models import ReportEligibility
from sqlalchemy import func, select, update
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


class OfficialResponses:
    def __init__(self):
        self.calls = []
        self.override = {}
        self.waiting = None
        self.release = None

    async def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if self.waiting and path.endswith('userAccessToken'):
            self.waiting.set()
            await self.release.wait()
        if path in self.override:
            value = self.override[path]
            return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
        if path.endswith('userAccessToken'):
            body = json.loads(request.content)
            return httpx.Response(200, json={'accessToken': body['code'], 'corpId': 'corp-test'})
        if path.endswith('/users/me'):
            return httpx.Response(200, json={'unionId': request.headers['x-acs-dingtalk-access-token'], 'nick': '同名员工'})
        if path.endswith('/accessToken'):
            return httpx.Response(200, json={'accessToken': 'controlled-enterprise-token'})
        body = parse_qs(request.content.decode())
        assert body['access_token'] == ['controlled-enterprise-token']
        if path.endswith('getbyunionid'):
            return httpx.Response(200, json={'errcode': 0, 'result': {'contact_type': 0, 'userid': 'u-' + body['unionid'][0]}})
        if path.endswith('/user/get'):
            userid = body['userid'][0]
            return httpx.Response(200, json={'errcode': 0, 'result': {'userid': userid, 'unionid': userid[2:], 'name': '同名员工', 'active': True, 'admin': True}})
        raise AssertionError('Unexpected provider endpoint')


def app_for(clients):
    return clients['admin']._transport.app


def browser(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(uuid4().hex, 123)), base_url='http://test', headers={'Origin': 'http://test'})


async def enable(setup, monkeypatch, enabled=True):
    settings, sessions, users, clients = setup
    original = routes_login_company
    async def company(db, settings):
        return await original(db, replace(settings, login_company_id=users['admin'].company_id))
    monkeypatch.setattr(routes, 'login_company', company)
    response = await clients['admin'].put('/api/v1/settings/login/dingtalk', json={'corpId': 'corp-test', 'clientId': 'client-test', 'secret': 'controlled-app-secret', 'enabled': enabled, 'expectedRevision': 0})
    assert response.status_code == 200, response.text
    provider = OfficialResponses()
    app_for(clients).state.dingtalk_provider = DingTalkProvider(httpx.MockTransport(provider))
    return provider


async def begin(client, path='/api/v1/auth/dingtalk/start', body=None):
    response = await client.post(path, json=body or {})
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()['url'])
    assert url.scheme == 'https' and url.netloc == 'login.dingtalk.com'
    query = parse_qs(url.query)
    assert query['scope'] == ['openid corpid']
    assert query['redirect_uri'] == ['http://test/api/v1/auth/dingtalk/callback']
    return query['state'][0]


async def complete(client, state, code='identity-one'):
    return await client.get('/api/v1/auth/dingtalk/callback', params={'state': state, 'authCode': code})


async def logged_in(client):
    response = await client.get('/api/v1/auth/me')
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf']
    return response.json()


@pytest.mark.asyncio
async def test_configuration_scoping_secret_revision_and_disabled_probe(setup, monkeypatch):
    settings, sessions, users, clients = setup
    admin = clients['admin']
    assert (await clients['employee'].get('/api/v1/settings/login/dingtalk')).status_code == 403
    assert (await admin.get('/api/v1/settings/login/dingtalk')).json()['hasSecret'] is False
    provider = await enable(setup, monkeypatch, enabled=False)
    saved = (await admin.get('/api/v1/settings/login/dingtalk')).json()
    assert saved['hasSecret'] and not saved['enabled'] and saved['verifiedAt'] is None
    assert 'controlled-app-secret' not in json.dumps(saved)
    assert (await admin.get('/api/v1/auth/providers')).json() == {'password': True, 'dingtalk': False}
    async with browser(app_for(clients)) as anon:
        assert (await anon.post('/api/v1/auth/dingtalk/start')).status_code == 409
    state = await begin(admin, '/api/v1/settings/login/dingtalk/probe')
    before = await logged_in(admin)
    result = await complete(admin, state)
    assert result.headers['location'] == 'http://test/settings/login?dingtalk=verified'
    assert (await logged_in(admin))['member']['id'] == before['member']['id']
    saved = (await admin.get('/api/v1/settings/login/dingtalk')).json()
    assert saved['verifiedAt']
    payload = {'corpId': saved['corpId'], 'clientId': saved['clientId'], 'secret': '', 'enabled': True, 'expectedRevision': saved['revision']}
    assert (await admin.put('/api/v1/settings/login/dingtalk', json=payload)).status_code == 200
    assert (await admin.put('/api/v1/settings/login/dingtalk', json=payload)).status_code == 409
    async with sessions() as db:
        config = await db.scalar(select(DingTalkConfig).where(DingTalkConfig.company_id == users['admin'].company_id))
        assert config.credential != 'controlled-app-secret'
        assert await db.scalar(select(func.count()).select_from(DingTalkIdentity).where(DingTalkIdentity.company_id == users['admin'].company_id)) == 0
    assert len(provider.calls) == 5
    assert all(not request.url.query for request in provider.calls)


@pytest.mark.asyncio
async def test_new_employee_reuses_identity_concurrently_and_keeps_local_password_disabled(setup, monkeypatch):
    settings, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    async with browser(app_for(clients)) as first, browser(app_for(clients)) as second:
        states = await asyncio.gather(begin(first), begin(second))
        results = await asyncio.gather(complete(first, states[0]), complete(second, states[1]))
        assert all(result.headers['location'].endswith('dingtalk=logged-in') for result in results)
        assert all(result.headers['referrer-policy'] == 'no-referrer' for result in results)
        a, b = await logged_in(first), await logged_in(second)
        assert a['member']['id'] == b['member']['id']
        assert a['member']['role'] == 'employee' and 'mustChangePassword' not in a['member'] and not a['member']['hasPassword']
        assert a['member']['username'].startswith('dd_')
        assert (await first.post('/api/v1/auth/login', json={'username': a['member']['username'], 'password': 'controlled-test-password'})).status_code == 401
        async with sessions() as db:
            actor = await db.get(Member, a['member']['id'])
            assert actor.password_hash is None
            assert await db.scalar(select(func.count()).select_from(DingTalkIdentity).where(DingTalkIdentity.company_id == actor.company_id)) == 1
            assert await db.scalar(select(ReportEligibility.id).where(ReportEligibility.owner_id == actor.id))
            grant = await db.scalar(select(DingTalkAuthorization).where(DingTalkAuthorization.state_hash == digest(states[0])))
            assert grant.state_hash != states[0] and grant.browser_hash != first.cookies.get(BROWSER_COOKIE, '')
        assert (await first.post('/api/v1/auth/dingtalk/account/unbind', json={'useDingTalk': True})).status_code == 409
        assert (await clients['admin'].patch('/api/v1/members/' + a['member']['id'], json={'active': False})).status_code == 200
        state = await begin(second)
        assert 'reason=denied' in (await complete(second, state)).headers['location']
        assert (await first.get('/api/v1/auth/me')).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize('path,data', [
    ('/v1.0/oauth2/userAccessToken', {'accessToken': 'fake', 'corpId': 'another-corp'}),
    ('/topapi/user/getbyunionid', {'errcode': 0, 'result': {'userid': 'u-identity-one', 'contact_type': 1}}),
    ('/topapi/v2/user/get', {'errcode': 60121, 'errmsg': 'secret-provider-error'}),
    ('/topapi/v2/user/get', {'errcode': 0, 'result': {'userid': 'u-identity-one', 'unionid': 'identity-one', 'active': False}}),
    ('/topapi/v2/user/get', {'errcode': 0, 'result': {'userid': 'u-wrong', 'unionid': 'identity-one', 'active': True}}),
])
async def test_company_member_checks_fail_closed(setup, monkeypatch, path, data):
    settings, sessions, users, clients = setup
    provider = await enable(setup, monkeypatch)
    provider.override[path] = data
    async with browser(app_for(clients)) as client:
        response = await complete(client, await begin(client))
        assert 'reason=denied' in response.headers['location']
        assert 'secret-provider-error' not in response.text + str(response.headers)
        assert not client.cookies.get(COOKIE)
    async with sessions() as db:
        assert not await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.company_id == users['admin'].company_id))
        assert await db.scalar(select(func.count()).select_from(Member).where(Member.company_id == users['admin'].company_id)) == 3


@pytest.mark.asyncio
async def test_state_browser_expiry_cancellation_replay_and_rotation(setup, monkeypatch):
    settings, sessions, users, clients = setup
    provider = await enable(setup, monkeypatch)
    async with browser(app_for(clients)) as one, browser(app_for(clients)) as two:
        state = await begin(one)
        assert 'reason=expired' in (await complete(two, state)).headers['location']
        responses = await asyncio.gather(complete(one, state), complete(one, state))
        assert sum('dingtalk=logged-in' in r.headers['location'] for r in responses) == 1
        assert len(provider.calls) == 5
        expired = await begin(one)
        async with sessions.begin() as db:
            await db.execute(update(DingTalkAuthorization).where(DingTalkAuthorization.state_hash == digest(expired)).values(expires_at=now() - timedelta(seconds=1)))
        assert 'reason=expired' in (await complete(one, expired)).headers['location']
        cancelled = await begin(one)
        result = await one.get('/api/v1/auth/dingtalk/callback', params={'state': cancelled, 'error': 'access_denied'})
        assert 'reason=cancelled' in result.headers['location']
        assert 'reason=expired' in (await complete(one, cancelled)).headers['location']
        assert len(provider.calls) == 5
        pending = await begin(one)
        provider.waiting, provider.release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(complete(one, pending))
        await asyncio.wait_for(provider.waiting.wait(), 5)
        changed = await clients['admin'].put('/api/v1/settings/login/dingtalk', json={'corpId': 'corp-test', 'clientId': 'client-test', 'secret': 'replacement-secret', 'enabled': True, 'expectedRevision': 1})
        assert changed.status_code == 200
        provider.release.set()
        assert 'reason=expired' in (await task).headers['location']
        changed_identity = await clients['admin'].put('/api/v1/settings/login/dingtalk', json={'corpId': 'different', 'clientId': 'client-test', 'secret': 'replacement', 'enabled': True, 'expectedRevision': 2})
        assert changed_identity.status_code == 409


@pytest.mark.asyncio
async def test_bind_preserves_existing_account_conflicts_and_revokes_old_sessions(setup, monkeypatch):
    settings, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    admin = clients['admin']
    assert (await admin.post('/api/v1/auth/dingtalk/account/bind', json={'currentPassword': 'wrong'})).status_code == 400
    original_session = admin.cookies.get(COOKIE)
    state = await begin(admin, '/api/v1/auth/dingtalk/account/bind', {'currentPassword': 'controlled-test-password'})
    assert 'dingtalk=bound' in (await complete(admin, state)).headers['location']
    identity = await logged_in(admin)
    assert identity['member']['id'] == users['admin'].id and identity['member']['role'] == 'admin'
    assert admin.cookies.get(COOKIE) != original_session
    employee = clients['employee']
    state = await begin(employee, '/api/v1/auth/dingtalk/account/bind', {'currentPassword': 'controlled-test-password'})
    assert 'reason=conflict' in (await complete(employee, state)).headers['location']
    async with browser(app_for(clients)) as anon:
        assert 'dingtalk=logged-in' in (await complete(anon, await begin(anon))).headers['location']
        assert (await logged_in(anon))['member']['id'] == users['admin'].id
        assert (await admin.post('/api/v1/auth/dingtalk/account/unbind', json={'currentPassword': 'controlled-test-password'})).status_code == 200
        assert (await anon.get('/api/v1/auth/me')).status_code == 401
    assert (await admin.get('/api/v1/auth/me')).status_code == 401


@pytest.mark.asyncio
async def test_password_proof_same_identity_one_time_and_session_revocation(setup, monkeypatch):
    settings, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    async with browser(app_for(clients)) as client, browser(app_for(clients)) as other:
        await complete(client, await begin(client))
        identity = await logged_in(client)
        await complete(other, await begin(other))
        await logged_in(other)
        wrong = await begin(client, '/api/v1/auth/dingtalk/account/reauth')
        assert 'reason=denied' in (await complete(client, wrong, 'someone-else')).headers['location']
        assert (await client.post('/api/v1/auth/password', json={'newPassword': 'new-controlled-password', 'useDingTalk': True})).status_code == 400
        state = await begin(client, '/api/v1/auth/dingtalk/account/reauth')
        assert 'dingtalk=verified' in (await complete(client, state)).headers['location']
        proof_cookie = client.cookies.get(PROOF_COOKIE)
        assert (await client.get('/api/v1/auth/dingtalk/account')).json()['passwordVerified']
        assert (await client.post('/api/v1/auth/password', json={'newPassword': 'new-controlled-password', 'useDingTalk': True})).status_code == 200
        assert (await other.get('/api/v1/auth/me')).status_code == 401
        login = await client.post('/api/v1/auth/login', json={'username': identity['member']['username'], 'password': 'new-controlled-password'})
        assert login.status_code == 200
        await logged_in(client)
        client.cookies.set(PROOF_COOKIE, proof_cookie, path='/api/v1/auth')
        assert (await client.post('/api/v1/auth/password', json={'newPassword': 'new-controlled-password-again', 'useDingTalk': True})).status_code == 400
        async with sessions() as db:
            member = await db.get(Member, identity['member']['id'])
            assert member.password_hash and member.password_hash != 'new-controlled-password'
        # A later DingTalk login preserves the password without a forced-change step.
        await complete(other, await begin(other))
        member = (await logged_in(other))['member']
        assert member['hasPassword'] and 'mustChangePassword' not in member
        assert (await other.get('/api/v1/work-items')).status_code == 200


@pytest.mark.asyncio
async def test_company_resolution_never_picks_first_and_account_csrf_required(setup):
    settings, sessions, users, clients = setup
    app = create_app(replace(settings, login_company_id=''))
    async with browser(app) as client:
        assert (await client.get('/api/v1/auth/providers')).json()['dingtalk'] is False
        assert (await client.post('/api/v1/auth/dingtalk/start')).status_code == 409
        assert (await client.post('/api/v1/auth/dingtalk/start', headers={'Origin': 'https://evil.test'})).status_code == 403
    client = clients['employee']
    assert (await client.post('/api/v1/auth/dingtalk/account/reauth', headers={'X-CSRF-Token': ''})).status_code == 403
    assert (await client.get('/api/v1/auth/dingtalk/account')).status_code == 200
    assert (await client.get('/api/v1/work-items')).status_code == 200
    await app.state.sessions.kw['bind'].dispose()


@pytest.mark.asyncio
async def test_missing_master_key_does_not_replace_dingtalk_credentials(setup, monkeypatch):
    settings, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    from app.security.secrets import SecretUnavailable
    monkeypatch.setattr(cli, 'Settings', lambda: settings)
    settings.model_key_file.unlink()
    with pytest.raises(SecretUnavailable):
        await cli_prepare_model_key()
    assert not settings.model_key_file.exists()
    assert (await clients['admin'].put('/api/v1/settings/login/dingtalk', json={'corpId': 'corp-test', 'clientId': 'client-test', 'secret': '', 'enabled': False, 'expectedRevision': 1})).status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['reset', 'password', 'disable'])
async def test_password_login_cannot_issue_after_concurrent_revocation(setup, monkeypatch, change):
    settings, sessions, users, clients = setup
    verify = api_module_verify_password
    waiting, release = asyncio.Event(), asyncio.Event()
    blocked_once = False
    async def paused_verify(value, stored):
        nonlocal blocked_once
        result = await verify(value, stored)
        if not blocked_once:
            blocked_once = True
            waiting.set()
            await release.wait()
        return result
    monkeypatch.setattr(api_module, 'verify_password', paused_verify)
    async with browser(app_for(clients)) as client:
        task = asyncio.create_task(client.post('/api/v1/auth/login', json={'username': users['employee'].username, 'password': 'controlled-test-password'}))
        await asyncio.wait_for(waiting.wait(), 5)
        if change == 'reset':
            changed = await clients['admin'].post('/api/v1/members/' + users['employee'].id + '/reset-password', json={'password': 'changed-controlled-password'})
        elif change == 'password':
            changed = await clients['employee'].post('/api/v1/auth/password', json={'currentPassword': 'controlled-test-password', 'newPassword': 'changed-controlled-password'})
        else:
            changed = await clients['admin'].patch('/api/v1/members/' + users['employee'].id, json={'active': False})
        assert changed.status_code == 200
        release.set()
        assert (await task).status_code == 401
        assert not client.cookies.get(COOKIE)
        async with sessions() as db:
            assert not await db.scalar(select(Session.id).where(Session.member_id == users['employee'].id))


@pytest.mark.asyncio
async def test_sensitive_route_rate_limits_complete_with_the_three_connection_pool(setup, monkeypatch):
    settings, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    # Force contention at the rate transaction, before AUTH's company lock.
    # All five operations use the same 3-connection application pool.
    requests = [
        clients['admin'].post('/api/v1/settings/login/dingtalk/probe', json={}),
        clients['employee'].post('/api/v1/auth/dingtalk/account/bind', json={'currentPassword': 'wrong'}),
        clients['employee'].post('/api/v1/auth/dingtalk/account/reauth', json={}),
        clients['employee'].post('/api/v1/auth/dingtalk/account/unbind', json={'currentPassword': 'wrong'}),
        clients['employee'].post('/api/v1/auth/password', json={'currentPassword': 'wrong', 'newPassword': 'controlled-new-password'}),
    ]
    results = await asyncio.wait_for(asyncio.gather(*requests), 10)
    assert [result.status_code for result in results] == [200, 400, 409, 400, 400]
    # Failure counts survive each route's business rollback.
    from app.modules.auth.models import LoginAttempt
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity == digest('dingtalk-account:' + users['employee'].id))) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload,reason,vendor_code,vendor_sub_code', [
    (200, {'errcode': 60011}, 'permission', 60011, None),
    (200, {'errcode': 88, 'sub_code': '60011'}, 'permission', 88, 60011),
    (403, {'errcode': '60011'}, 'permission', 60011, None),
    (200, {'errcode': 88, 'sub_code': 'private-nonnumeric-code'}, 'denied', 88, None),
])
async def test_permission_failure_has_safe_correlated_diagnostics(setup, monkeypatch, caplog, status, payload, reason, vendor_code, vendor_sub_code):
    settings, sessions, users, clients = setup
    provider = await enable(setup, monkeypatch)
    private_message = 'private-upstream-message controlled-app-secret controlled-enterprise-token'
    provider.override['/topapi/user/getbyunionid'] = httpx.Response(status, json={**payload, 'errmsg': private_message, 'sub_msg': private_message})
    caplog.set_level(logging.INFO, logger='uvicorn.error.paa_dingtalk')
    async with browser(app_for(clients)) as client:
        state = await begin(client)
        browser_secret = client.cookies.get(BROWSER_COOKIE)
        response = await complete(client, state, 'controlled-private-auth-code')
        assert 'reason=' + reason in response.headers['location']
        assert not client.cookies.get(COOKIE)
        diagnostics = [json.loads(record.getMessage().removeprefix('dingtalk ')) for record in caplog.records if record.name == 'uvicorn.error.paa_dingtalk']
        assert diagnostics == [{
            'requestId': response.headers['x-request-id'],
            'reason': reason,
            'stage': 'union_lookup',
            'httpStatus': status,
            'vendorCode': vendor_code,
            'vendorSubCode': vendor_sub_code,
        }]
        for sensitive in (state, browser_secret, 'controlled-private-auth-code', 'controlled-app-secret', 'controlled-enterprise-token', 'private-upstream-message', 'private-nonnumeric-code', 'corp-test', 'client-test'):
            assert sensitive not in caplog.text
            assert sensitive not in response.text + str(response.headers)
    async with sessions() as db:
        assert not await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.company_id == users['admin'].company_id))
        assert await db.scalar(select(func.count()).select_from(Member).where(Member.company_id == users['admin'].company_id)) == 3
