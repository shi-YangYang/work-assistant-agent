"""Opt-in Docker Desktop rehearsal; no real DingTalk account or model calls."""
import asyncio
from contextlib import AsyncExitStack
import json
import os
from time import perf_counter
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import delete, select

from _support.http.dingtalk import complete, enable, logged_in
from _support.http.login_proxy import login_proxy
from app.modules.auth.dingtalk.rate_limit import RATE_COOKIE
from app.modules.auth.models import DingTalkIdentity, LoginAttempt
from app.modules.auth.sessions import COOKIE, digest
from app.tasks.models import Job

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    not os.getenv('PAA_TEST_LOGIN_PROXY_IMAGE'), reason='Opt in with a local service image and Docker Desktop',
)]


@pytest.mark.parametrize('count', [50, 100])
async def test_real_proxy_office_login_burst_and_forwarded_header_spoofing(setup, monkeypatch, tmp_path, count):
    settings, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    keys = set()
    try:
        async with login_proxy(settings, users['admin'].company_id, tmp_path) as (origin, proxy_ip):
            async with AsyncExitStack() as stack:
                async def record(response):
                    token = response.cookies.get(RATE_COOKIE)
                    if token:
                        keys.add(digest('dingtalk:login:browser:' + token))
                async def browser():
                    return await stack.enter_async_context(httpx.AsyncClient(
                        base_url=origin, headers={'Origin': origin}, timeout=20, trust_env=False,
                        event_hooks={'response': [record]},
                    ))
                observer = await browser()
                identity = (await observer.get('/api/v1/test/client')).json()
                assert identity['host'] != proxy_ip
                assert identity['scheme'] == 'http'
                keys.add(digest('dingtalk:login:ip:' + identity['host']))
                spoofed = await observer.get('/api/v1/test/client', headers={
                    'X-Forwarded-For': '203.0.113.99', 'X-Forwarded-Proto': 'https',
                })
                assert spoofed.json() == identity
                members = [await browser() for _ in range(count)]
                admin = await browser()
                admin.headers['Cookie'] = COOKIE + '=' + clients['admin'].cookies.get(COOKIE)
                admin.headers['X-CSRF-Token'] = clients['admin'].headers['X-CSRF-Token']

                async def login(client):
                    started = perf_counter()
                    response = await client.post('/api/v1/auth/dingtalk/start')
                    assert response.status_code == 200, response.text
                    state = parse_qs(urlsplit(response.json()['url']).query)['state'][0]
                    code = 'proxy-' + uuid4().hex
                    callback = await complete(client, state, code)
                    assert callback.headers['location'].endswith('dingtalk=logged-in')
                    member = await logged_in(client)
                    return code, member['member']['id'], perf_counter() - started

                async def existing_user():
                    for _ in range(5):
                        assert (await admin.get('/api/v1/work-items')).status_code == 200
                    response = await admin.post('/api/v1/messages', json={'text': '隔离登录压力测试', 'newConversation': True},
                                                headers={'Idempotency-Key': uuid4().hex})
                    assert response.status_code == 202
                    return response.json()['jobId']

                started = perf_counter()
                *results, job_id = await asyncio.wait_for(asyncio.gather(*(login(c) for c in members), existing_user()), 25)
                elapsed = perf_counter() - started
                assert len({row[1] for row in results}) == count
                async with sessions() as db:
                    links = (await db.scalars(select(DingTalkIdentity).where(DingTalkIdentity.company_id == users['admin'].company_id))).all()
                    assert {(link.union_id, link.member_id) for link in links} == {(r[0], r[1]) for r in results}
                    assert (await db.get(Job, job_id)).state == 'queued'
                # An attacker cannot obtain extra network budget by rotating
                # cookies and forging a different forwarded address each time.
                for i in range(120 - count):
                    observer.cookies.clear()
                    response = await observer.post('/api/v1/auth/dingtalk/start', headers={'X-Forwarded-For': f'203.0.113.{i + 1}'})
                    assert response.status_code == 200
                observer.cookies.clear()
                limited = await observer.post('/api/v1/auth/dingtalk/start', headers={'X-Forwarded-For': '198.51.100.99'})
                assert limited.status_code == 429
                assert limited.json()['error']['code'] == 'login_network_rate_limited'
                assert 1 <= int(limited.headers['Retry-After']) <= 60
                durations = sorted(r[2] for r in results)
                print(json.dumps({'browsers': count, 'completed': count, 'elapsedSeconds': round(elapsed, 3),
                                  'loginP95Seconds': round(durations[int(count * .95) - 1], 3),
                                  'existingUserReadAndMessage': 'passed', 'spoofedHeaders': 'ignored'}))
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(LoginAttempt).where(LoginAttempt.identity.in_(keys)))
