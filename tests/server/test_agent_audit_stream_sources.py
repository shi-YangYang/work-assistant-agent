"""Spec 059: preserve deliverable security assertions on Redis/SSE protocol v2."""
import asyncio
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.agent.context.history import conversation_history
from app.agent.tools.team import query_team_business
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.messages.models import Message
from app.security.access import scope
from app.tasks.context import InputChanged
from app.tasks.streaming.publisher import ReplyPublisher
from app.tasks.feedback.feedback import events, snapshot
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/agent-audit'))
from faults import evidence
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from test_business_actions import create, finish, runtime
from test_deliverables import read_plan, save_plan

pytestmark = pytest.mark.asyncio


def token(client):
    return hashlib.sha256(client.cookies.get('paa_company_session').encode()).hexdigest()


async def preview(context, client, publisher):
    temporary = await publisher.store.snapshot(publisher.identity)
    assert temporary is not None
    return await snapshot(context.sessions, token(client), context.job_id, temporary=temporary)


async def sse_state(context, client, state):
    source = events(context.sessions, token(client), context.job_id, settings=context.settings, version=2)
    try:
        async with asyncio.timeout(3):
            async for raw in source:
                if not raw.startswith('event: '):
                    continue
                name = raw.split('\n', 1)[0].removeprefix('event: ')
                data = json.loads(raw.split('data: ', 1)[1])
                if name == 'reply_withdrawn' and state == 'withdrawn':
                    return data
                if name in ('reply_sync', 'reply_delta') and data.get('state') == state:
                    return data
    finally:
        await source.aclose()



@pytest.mark.parametrize('ending', ['cancelled', 'failed'])
@pytest.mark.parametrize('entry', ['history', 'catalog', 'body', 'selected'])
async def test_v2_team_result_from_unfinished_task_never_becomes_streamable(setup, monkeypatch, ending, entry):
    settings, sessions, users, clients = setup
    marker = '团队来源的受控敏感正文'
    await create(clients['employee'], title='团队来源测试', summary=marker)
    context, sent = await runtime(setup, '查询团队并整理个人方案', who='admin')
    result = json.loads(await query_team_business.coroutine(
        runtime=SimpleNamespace(context=context), employee_ids=[users['employee'].id]))
    assert result['items'][0]['content']['summary'] == marker
    plan = await save_plan(context, title=marker, body=marker)
    assert plan['state'] == 'succeeded'
    async with sessions() as db:
        assert (await db.get(Deliverable, plan['id'])).access['team'] is True
        assert not (await db.get(Message, sent['messageId'])).access.get('team')
    if ending == 'cancelled':
        response = await clients['admin'].post('/api/v1/jobs/' + sent['jobId'] + '/cancel',
            json={'expectedAttempt': 0, 'expectedFence': context.fence})
        assert response.status_code == 200
    else:
        async with sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.lease_until = 'failed', None

    context, followup = await runtime(setup, '解释刚才已保存的个人方案', who='admin')
    assert followup['conversationId'] == sent['conversationId']
    if entry in ('history', 'selected'):
        if entry == 'selected':
            # An explicit older selection remains relevant outside the catalog page.
            async def empty_catalog(*args):
                return []
            monkeypatch.setattr('app.agent.context.deliverable_context.conversation_deliverables', empty_catalog)
            async with sessions.begin() as db:
                message = await db.get(Message, followup['messageId'])
                message.deliverable_reference = {'id': plan['id'], 'revision': 1, 'itemIds': []}
        async with sessions() as db:
            job = await db.get(Job, context.job_id)
        history = await conversation_history(context, job, [])
        assert marker in str(history)
        assert not context.deliverable_reads
    else:
        restored = await read_plan(context, plan['id'] if entry == 'body' else '')
        assert marker == (restored['body'] if entry == 'body' else restored['items'][0]['title'])
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.access['team'] is True
        assert job.result['deliverableSources'][plan['id']] == {'revision': 1, 'readRevisions': [1]}
        if entry != 'body':
            assert not job.result.get('deliverableReads')
    # A fresh runtime must recover the persisted dependency even after a tool cache hit.
    publisher = ReplyPublisher(replace(context), 'team-result')
    await publisher.start()
    await publisher.write(marker)
    await publisher.drain()
    checked = await preview(context, clients['admin'], publisher)
    assert checked['replyStream']['state'] == 'withdrawn'
    assert checked['replyStream']['text'] == ''
    withdrawn = await sse_state(context, clients['admin'], 'withdrawn')
    assert not withdrawn.get('text')
    await publisher.close()
    evidence(f'v2-team-{ending}-{entry}', {'preview': checked['replyStream'], 'sse': withdrawn})
    # Buffering cannot make the authorized result itself unavailable.
    assert (await clients['admin'].get('/api/v1/deliverables/' + plan['id'])).json()['body'] == marker
    if ending == 'cancelled' and entry == 'history':
        from test_response_delivery import model
        async with sessions() as db:
            job = await db.get(Job, context.job_id)
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            await process_job(job, sessions, settings, saver, model=model(answer=marker))
        message = (await clients['admin'].get('/api/v1/messages/' + followup['messageId'])).json()
        assert message['job']['state'] == 'awaiting_input', message
        assert message['job']['taskOutcome']['state'] == 'completed'
        assert marker in message['reply']


@pytest.mark.parametrize('change', ['revision', 'access', 'team', 'removed_revision', 'file_source'])
async def test_v2_result_dependency_is_rechecked_on_preview_read_and_publish(setup, change):
    _, sessions, users, clients = setup
    context, _ = await runtime(setup, '保存本人方案', who='admin')
    plan = await save_plan(context, title='本人方案', body='本人材料')
    await finish(context)
    context, sent = await runtime(setup, '解释本人方案', who='admin')
    assert (await read_plan(context, plan['id']))['body'] == '本人材料'
    publisher = ReplyPublisher(context, 'personal-result')
    await publisher.start()
    await publisher.write('本人的流式分析')
    feedback_url = '/api/v1/jobs/' + sent['jobId'] + '/feedback'
    await publisher.drain()
    assert (await preview(context, clients['admin'], publisher))['replyStream']['text'] == '本人的流式分析'
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert job.feedback['replyStreamSource']['deliverables'][plan['id']]['revision'] == 1
        item = await db.get(Deliverable, plan['id'])
        record = await db.scalar(select(DeliverableRevision).where(DeliverableRevision.deliverable_id == item.id))
        if change == 'revision':
            item.revision += 1
        elif change == 'access':
            item.owner_id = users['peer'].id
        elif change == 'team':
            item.access = {**scope(users['admin']), 'team': True}
        elif change == 'removed_revision':
            await db.delete(record)
        else:
            record.files = [{'sources': [{'kind': 'attachment', 'id': 'removed-source', 'revision': 1, 'sha256': 'gone'}]}]
    # No republish: the current preview/SSE reader independently rechecks sources.
    checked = await preview(context, clients['admin'], publisher)
    assert checked['replyStream']['state'] == 'withdrawn'
    assert checked['replyStream']['text'] == ''
    assert 'replyStreamSource' not in json.dumps(checked)
    evidence('v2-source-' + change, {'preview': checked['replyStream']})
    if change == 'team':
        await publisher.write('迟到的团队正文', force=True)
        await publisher.drain()
        assert (await publisher.store.snapshot(publisher.identity))['text'] == ''
        withdrawn = await sse_state(context, clients['admin'], 'withdrawn')
        assert not withdrawn.get('text')
    else:
        withdrawn = await sse_state(context, clients['admin'], 'withdrawn')
        assert not withdrawn.get('text')
        with pytest.raises((InputChanged, HTTPException)):
            await publisher.write('失效后迟到的正文', force=True)
            await publisher.drain()
    await publisher.close()


async def test_v2_reading_historical_revision_and_saving_new_version_keep_personal_streaming(setup):
    context, _ = await runtime(setup, '保存本人方案')
    plan = await save_plan(context, title='本人方案', body='初版')
    second = await save_plan(context, title='本人方案', body='新版', deliverable_id=plan['id'], expected_revision=1, step=2)
    assert second['revision'] == 2
    await finish(context)
    context, sent = await runtime(setup, '比较历史方案')
    assert (await read_plan(context, plan['id'], 1))['body'] == '初版'
    assert (await read_plan(context, plan['id'], 2))['body'] == '新版'
    third = await save_plan(context, title='本人方案', body='继续完善', deliverable_id=plan['id'], expected_revision=2)
    assert third['revision'] == 3
    # Same-step recovery of a saved result remains idempotent and does not taint scope.
    replay = await save_plan(context, title='本人方案', body='继续完善', deliverable_id=plan['id'], expected_revision=2)
    assert replay['revision'] == 3
    publisher = ReplyPublisher(context, 'personal-history')
    await publisher.start()
    await publisher.write('按个人历史材料整理')
    await publisher.drain()
    assert (await preview(context, setup[3]['employee'], publisher))['replyStream']['text'] == '按个人历史材料整理'
    streamed = await sse_state(context, setup[3]['employee'], 'streaming')
    assert streamed['text'] == '按个人历史材料整理'
    await publisher.close()
    evidence('v2-historical-personal', {'revision': third['revision'], 'replayRevision': replay['revision'], 'sse': streamed})
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.feedback['replyStreamSource']['deliverables'][plan['id']] == {'revision': 3, 'readRevisions': [1, 2, 3]}
