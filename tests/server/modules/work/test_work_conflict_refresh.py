"""A rejected work write can refresh its source without weakening stale-read guards."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.actions.operations import execute
from app.agent.runtime.middleware import ToolBoundary
from app.integrations.models.transport import ProviderError
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.nodes.node_execution import check, initialize
from _support.agent.business_actions import read_work
from _support.agent.execution_permissions import mode_runtime
from _support.agent.work_execution_history import WorkJudge
from _support.work.work_records import create, key
from _support.agent.work_conflict_refresh import tool_request

pytestmark = pytest.mark.asyncio


async def prepare_conflict(setup, *, during_authorization=False):
    client = setup[3]['employee']
    work = await create(client)
    context, _ = await mode_runtime(setup, 'full', '在正文追加验收环节，遇到版本冲突先重新读取，保留其他内容')
    context.node_retry, context.intent_model = True, WorkJudge()
    await initialize(context, 'work-conflict')
    boundary = ToolBoundary()

    async def read(request):
        detail = await read_work(context, work['id'])
        return ToolMessage(content=json.dumps(detail), tool_call_id=request.tool_call['id'], name='get_work_item')

    await boundary.awrap_tool_call(tool_request(context, 'get_work_item', {'work_id': work['id']}, 'read-before'), read)
    patch = {'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '验收环节'}]}]}]}

    async def manual_write():
        manual = await client.patch('/api/v1/work-items/' + work['id'],
                                    json={'expectedRevision': 1, 'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '人工新增内容'}]}]}]}, headers=key())
        assert manual.status_code == 200, manual.text

    if during_authorization:
        class ConcurrentJudge(WorkJudge):
            async def ainvoke(self, messages):
                if not self.inputs:
                    await manual_write()
                return await super().ainvoke(messages)
        context.intent_model = ConcurrentJudge()

    async def concurrent_write(request):
        if not during_authorization:
            await manual_write()
        with pytest.raises(HTTPException) as error:
            await execute(context, **request.tool_call['args'])
        assert error.value.status_code == 409
        return ToolMessage(content=json.dumps({'state': 'conflict', 'message': error.value.detail['message']}),
                           tool_call_id=request.tool_call['id'], name='execute_business_action')

    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1, 'changes': patch}
    result = await boundary.awrap_tool_call(tool_request(context, 'execute_business_action', args, 'conflict-write'), concurrent_write)
    assert json.loads(result.content)['state'] == 'conflict'
    assert context.read_versions[work['id']] == 1 and context.refresh_work_versions == {work['id']: 1}
    if during_authorization:
        from sqlalchemy import select
        from app.modules.operations.models import BusinessAction
        async with context.sessions() as db:
            job = await db.get(Job, context.job_id)
            assert job.result['nodeExecution']['refreshWorkVersions'] == {work['id']: 1}
            assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == job.target_id))
    return work, context, patch


@pytest.mark.parametrize('during_authorization', [False, True])
async def test_work_conflict_reloads_after_restart_before_safely_appending(setup, during_authorization):
    work, original, patch = await prepare_conflict(setup, during_authorization=during_authorization)
    context = replace(original, read_versions={}, refresh_work_versions={})
    await initialize(context, 'work-conflict')
    assert context.node_scope == original.node_scope
    assert context.read_versions[work['id']] == 1 and context.refresh_work_versions == {work['id']: 1}
    with pytest.raises(ProviderError, match='已变化'):
        await check(context)
    await check(context, allow_work_refresh=True)

    boundary = ToolBoundary()
    model_request = SimpleNamespace(runtime=SimpleNamespace(context=context), system_message=None, messages=[],
                                    tools=[SimpleNamespace(name=name) for name in ('get_work_item', 'execute_business_action', 'finish_task')],
                                    override=lambda **values: values)
    model_handler = AsyncMock(return_value='reread-plan')
    assert await boundary.awrap_model_call(model_request, model_handler) == 'reread-plan'
    options = model_handler.call_args.args[0]
    assert [tool.name for tool in options['tools']] == ['get_work_item']
    assert options['tool_choice']['function']['name'] == 'get_work_item'
    for name, args in [('finish_task', {}), ('execute_business_action', {}), ('get_work_item', {'work_id': work['id'], 'body_start': 20})]:
        handler = AsyncMock()
        blocked = await boundary.awrap_tool_call(tool_request(context, name, args, 'blocked-' + name), handler)
        assert json.loads(blocked.content)['state'] == 'conflict'
        handler.assert_not_awaited()

    async def read(request):
        detail = await read_work(context, work['id'])
        return ToolMessage(content=json.dumps(detail), tool_call_id=request.tool_call['id'], name='get_work_item')

    refreshed = await boundary.awrap_tool_call(tool_request(context, 'get_work_item', {'work_id': work['id']}, 'read-latest'), read)
    detail = json.loads(refreshed.content)
    assert '人工新增内容' in detail['bodyText'] and detail['revision'] == 2
    assert context.read_versions[work['id']] == 2 and not context.refresh_work_versions
    await check(context)

    async def write(request):
        result = await execute(context, **request.tool_call['args'])
        return ToolMessage(content=json.dumps(result), tool_call_id=request.tool_call['id'], name='execute_business_action')

    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 2, 'changes': patch}
    saved = await boundary.awrap_tool_call(tool_request(context, 'execute_business_action', args, 'write-latest'), write)
    assert json.loads(saved.content)['state'] == 'succeeded', saved.content
    detail = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert detail['revision'] == 3 and detail['bodyText'].endswith('人工新增内容\n验收环节')
    assert detail['body']['content'][0] == work['body']['content'][0]
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['nodeExecution']['refreshWorkVersions'] == {}
        assert job.result['nodeExecution']['readVersions'][work['id']] == 3


@pytest.mark.parametrize('change', ['deleted', 'permission'])
async def test_conflict_refresh_cannot_bypass_deleted_or_restricted_work(setup, change):
    work, context, _ = await prepare_conflict(setup)
    async with context.sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        if change == 'deleted':
            row.deleted = True
        else:
            row.access = {**row.access, 'team': True}
    with pytest.raises(HTTPException) as error:
        await check(context, allow_work_refresh=True)
    assert error.value.status_code == (404 if change == 'deleted' else 403)
    assert context.read_versions[work['id']] == 1 and context.refresh_work_versions == {work['id']: 1}
