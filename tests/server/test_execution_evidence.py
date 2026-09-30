"""Saved observations remain readable without rerunning, within source permissions."""
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agent.context.history import conversation_history
from app.agent.tools.execution import read_execution
from app.modules.executions.models import SandboxExecution
from app.modules.messages.models import Message
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from test_business_actions import runtime, finish
from test_company import keyed
from test_sandbox_execution import receipts, run

pytestmark = pytest.mark.asyncio


async def followup(setup, conversation_id=None, who='employee'):
    settings, sessions, users, clients = setup
    response = await clients[who].post('/api/v1/messages', headers=keyed(), json={
        'text': '刚才实际输出是什么？不要重新运行。',
        **({'conversationId': conversation_id} if conversation_id else {'newConversation': True})})
    assert response.status_code == 202, response.text
    job = await claim(sessions, users[who].id)
    return RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)


async def read(context, identifier='', offset=0):
    return json.loads(await read_execution.coroutine(SimpleNamespace(context=context), identifier, offset))


async def test_followup_reads_persisted_code_output_without_running_or_sandbox_connection(setup, receipts):
    context, sent = await runtime(setup, '做一个计算')
    first = await run(context)
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    history = await conversation_history(context, job, '')
    directory = next(message.content for message in history if '已保存的执行记录目录' in str(message.content))
    assert first['executionId'] in directory and 'print(3)' not in directory
    listing = await read(context)
    assert listing['items'][0]['executionId'] == first['executionId']
    result = await read(context, first['executionId'])
    assert result['code'] == 'print(3)' and result['stdout'] == '3'
    assert result['exitCode'] == 0 and result['state'] == 'succeeded'
    assert result['historical'] and result['evidenceType'] == 'execution_receipt'
    assert result['title'] == '计算结果' and receipts.count == 1
    assert not {'key', 'jobId', 'fence', 'pythonVersion'} & result.keys()


@pytest.mark.parametrize('who', ['employee', 'peer', 'admin', 'outsider'])
async def test_receipts_never_cross_conversation_owner_or_company(setup, receipts, who):
    context, _ = await runtime(setup)
    first = await run(context)
    await finish(context)
    other = await followup(setup, who=who)
    assert (await read(other))['items'] == []
    assert (await read(other, first['executionId']))['state'] == 'unavailable'
    assert receipts.count == 1


@pytest.mark.parametrize('revoked', ['message', 'access', 'attachment'])
async def test_deleted_or_revoked_sources_hide_receipts(setup, receipts, revoked):
    context, sent = await runtime(setup)
    first = await run(context)
    await finish(context)
    async with setup[1].begin() as db:
        row = await db.get(SandboxExecution, first['executionId'])
        if revoked == 'message':
            (await db.get(Message, row.message_id)).deleted = True
        elif revoked == 'access':
            # Even when Message.access has no team references, the original
            # job may have embedded a restricted team query into its code.
            origin = await db.get(Job, row.job_id)
            origin.access = {'team': True, 'actorId': context.owner_id, 'companyId': context.company_id, 'reads': {}}
        else:
            row.sources = [{'kind': 'attachment', 'id': str(uuid4()), 'sha256': 'missing', 'revision': 1}]
    context = await followup(setup, sent['conversationId'])
    assert (await read(context))['items'] == []
    assert (await read(context, first['executionId']))['state'] == 'unavailable'


async def test_execution_text_and_directory_are_bounded_and_old_receipts_stay_honest(setup, receipts):
    context, sent = await runtime(setup)
    first = await run(context)
    await finish(context)
    async with setup[1].begin() as db:
        row = await db.get(SandboxExecution, first['executionId'])
        row.code = 'x' * 3001
        row.result = {'stdout': 'y' * 6001, 'stderr': 'failure', 'exitCode': 1}
        row.state = 'failed'
        for index in range(10):
            db.add(SandboxExecution(company_id=row.company_id, owner_id=row.owner_id,
                key=uuid4().hex, job_id=row.job_id, conversation_id=row.conversation_id,
                message_id=row.message_id, fence=row.fence, code=str(index), state='succeeded', result={}))
    context = await followup(setup, sent['conversationId'])
    listing = await read(context)
    assert len(listing['items']) == 10 and listing['nextOffset'] == 10
    tail = await read(context, offset=listing['nextOffset'])
    assert len(tail['items']) == 1 and tail['nextOffset'] is None
    first_page = await read(context, first['executionId'])
    assert first_page['title'] == 'Python 执行' and first_page['state'] == 'failed'
    assert first_page['contentTruncated'] and first_page['nextOffset'] == 3000
    second = await read(context, first['executionId'], 3000)
    third = await read(context, first['executionId'], 6000)
    assert first_page['code'] + second['code'] + third['code'] == 'x' * 3001
    assert first_page['stdout'] + second['stdout'] + third['stdout'] == 'y' * 6001
    assert third['nextOffset'] is None and receipts.count == 1
    assert (await read(context, first['executionId'], -1))['state'] == 'unavailable'
    assert (await read(context, first['executionId'], 6001))['state'] == 'unavailable'
