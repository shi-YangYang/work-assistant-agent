"""Shared controlled fixtures extracted from test_dingtalk."""
import httpx
import json
import app.modules.auth.dingtalk.router as routes
from dataclasses import replace
from app.integrations.dingtalk import DingTalkProvider
from app.modules.auth.dingtalk.service import login_company as routes_login_company
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
