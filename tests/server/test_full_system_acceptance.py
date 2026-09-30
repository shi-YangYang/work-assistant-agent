"""Spec044 API boundary and simultaneous-write assertions on the isolated fixture."""
import asyncio
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.db.idempotency import Idempotency
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkRevision
from app.tasks.models import Job

pytestmark = pytest.mark.asyncio


def evidence(name, values):
    directory = os.getenv('SPEC044_SERVER_EVIDENCE')
    if directory:
        target = Path(directory) / (name + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(values, ensure_ascii=False, indent=2) + '\n')


async def test_every_protected_registered_http_operation_rejects_anonymous_before_object_lookup(setup):
    _, _, _, clients = setup
    app = clients['employee']._transport.app
    public = {
        ('GET', '/api/v1/health'), ('GET', '/api/v1/auth/providers'),
        ('POST', '/api/v1/auth/login'), ('POST', '/api/v1/auth/logout'),
        ('POST', '/api/v1/auth/dingtalk/start'), ('GET', '/api/v1/auth/dingtalk/callback'),
        ('GET', '/api/v1/desktop/info'), ('POST', '/api/v1/desktop/login/start'),
        ('POST', '/api/v1/desktop/login/exchange'),
    }
    results = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://test'}) as client:
        for template, methods in app.openapi()['paths'].items():
            if not template.startswith('/api/v1/'):
                continue
            for method in sorted(value.upper() for value in methods if value not in ('head', 'options')):
                if (method, template) in public:
                    results.append({'operation': method + ' ' + template, 'status': 'N/A', 'reason': 'Explicit public/bootstrap/session-cleanup route; covered by protocol-specific tests'})
                    continue
                path = re.sub(r'\{[^}]+\}', str(uuid4()), template)
                response = await client.request(method, path, json={} if method not in ('GET', 'DELETE') else None)
                results.append({'operation': method + ' ' + template, 'status': response.status_code})
                assert response.status_code == 401, (method, template, response.status_code, response.text)
                assert not any(term in response.text for term in ('合成', 'password_hash', 'credential', 'traceback'))
    evidence('anonymous-api-operations', results)


async def test_twenty_five_simultaneous_same_key_writes_have_one_receipt_and_one_record(setup):
    _, sessions, users, clients = setup
    actor = users['employee']
    key = str(uuid4())
    payload = {'title': '并发只保存一次', 'summary': '固定内容', 'status': 'in_progress'}
    async def create():
        return await clients['employee'].post('/api/v1/work-items', json=payload, headers={'Idempotency-Key': key})
    responses = await asyncio.gather(*(create() for _ in range(25)))
    assert {response.status_code for response in responses} == {201}
    assert len({json.dumps(response.json(), sort_keys=True) for response in responses}) == 1
    identifier = responses[0].json()['id']
    conflict = await clients['employee'].post('/api/v1/work-items', json={**payload, 'title': '不同内容'}, headers={'Idempotency-Key': key})
    assert conflict.status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == actor.id)) == 1
        assert await db.scalar(select(func.count()).select_from(WorkRevision).where(WorkRevision.work_id == identifier)) == 1
        receipts = (await db.scalars(select(Idempotency).where(Idempotency.owner_id == actor.id, Idempotency.key == key))).all()
        assert len(receipts) == 1 and receipts[0].response['id'] == identifier
    evidence('concurrent-idempotency', {'requests': 25, 'createdWorks': 1, 'revisions': 1, 'receipts': 1, 'changedPayloadStatus': 409})


async def test_concurrent_versioned_edits_accept_exactly_one_and_preserve_winner(setup):
    _, sessions, _, clients = setup
    created = await clients['employee'].post('/api/v1/work-items', json={'title': '并发编辑'}, headers={'Idempotency-Key': str(uuid4())})
    assert created.status_code == 201
    identifier = created.json()['id']
    async def edit(index):
        return await clients['employee'].post(f'/api/v1/work-items/{identifier}/progress', json={'title': '并发编辑', 'expectedRevision': 1, 'summary': f'第{index}份修改'})
    responses = await asyncio.gather(*(edit(index) for index in range(10)))
    assert sorted(response.status_code for response in responses) == [200] + [409] * 9
    winner = next(response.json() for response in responses if response.status_code == 200)
    async with sessions() as db:
        saved = await db.get(WorkItem, identifier)
        assert saved.revision == 2 and saved.content['summary'] == winner['summary']
        assert await db.scalar(select(func.count()).select_from(WorkRevision).where(WorkRevision.work_id == identifier)) == 2
    for role in ('peer', 'outsider'):
        denied = await clients[role].post(f'/api/v1/work-items/{identifier}/progress', json={'title': '并发编辑', 'expectedRevision': 2, 'summary': '越权修改'})
        assert denied.status_code == 404
    evidence('concurrent-version', {'requests': 10, 'accepted': 1, 'conflicts': 9, 'storedRevision': 2, 'foreignDenied': 2})


async def test_parallel_message_replays_then_cancels_keep_one_job_and_terminal_fence(setup):
    _, sessions, users, clients = setup
    key = str(uuid4())
    async def send():
        return await clients['employee'].post('/api/v1/messages', json={'text': '只接受一条消息', 'newConversation': True}, headers={'Idempotency-Key': key})
    responses = await asyncio.gather(*(send() for _ in range(10)))
    assert {response.status_code for response in responses} == {202}
    assert len({response.json()['messageId'] for response in responses}) == 1
    identifier = responses[0].json()['jobId']
    async def cancel():
        return await clients['employee'].post(f'/api/v1/jobs/{identifier}/cancel', json={'expectedAttempt': 0, 'expectedFence': 0})
    cancellations = await asyncio.gather(*(cancel() for _ in range(10)))
    assert {response.status_code for response in cancellations} == {200}
    assert {response.json()['state'] for response in cancellations} == {'cancelled'}
    async with sessions() as db:
        job = await db.get(Job, identifier)
        assert job.fence == 1 and job.lease_until is None and job.state == 'cancelled'
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == users['employee'].id)) == 1
        assert await db.scalar(select(func.count()).select_from(Message).where(Message.owner_id == users['employee'].id)) == 1
    evidence('concurrent-message-cancel', {'sendRequests': 10, 'cancelRequests': 10, 'messages': 1, 'jobs': 1, 'finalFence': 1, 'state': 'cancelled'})
