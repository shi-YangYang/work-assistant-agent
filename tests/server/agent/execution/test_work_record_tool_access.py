"""Unavailable work references are business feedback, never file-read grants."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

from app.agent.runtime.middleware import ToolBoundary
from app.agent.tools.business.work_records import agent_work, WORK_RECORD_TOOLS
from app.modules.attachments.models import Attachment
from app.modules.executions.files import prepare_inputs
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.nodes.node_execution import check, initialize
from _support.materials.documents import run, upload
from _support.agent.execution_permissions import mode_runtime
from _support.work.work_records import create

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('status', [409, 500])
async def test_work_reference_unexpected_errors_still_propagate(monkeypatch, status):
    error = HTTPException(status, 'unexpected failure')
    monkeypatch.setattr('app.agent.tools.business.work_records.readable_work', AsyncMock(side_effect=error))
    with pytest.raises(HTTPException) as caught:
        await agent_work(None, None, None, 'work')
    assert caught.value is error


@pytest.mark.parametrize('denial', ['deleted', 'permission', 'missing_team_source'])
async def test_unavailable_work_tools_finish_without_reading_or_retrying(setup, denial):
    settings, sessions, users, clients = setup
    attachment = await upload(clients['employee'], 'restricted.txt', b'PRIVATE_CHECK_CODE_4739', 'text/plain')
    work = await create(clients['employee'], materials=[{'attachmentId': attachment['id']}])
    material = (await clients['employee'].get('/api/v1/work-items/' + work['id'] + '/materials')).json()['items'][0]
    async with sessions() as db:
        parser = await db.scalar(select(Job).where(Job.kind == 'document', Job.target_id == material['attachment']['id']))
    await run(settings, sessions, users, {'jobId': parser.id})
    who = 'admin' if denial == 'missing_team_source' else 'employee'
    context, _ = await mode_runtime(setup, 'full', '读取刚才工作里的材料；已删除或不可用请如实说明', who=who)
    context.node_retry = True
    await initialize(context, 'work-unavailable')
    async with sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        if denial == 'deleted':
            row.deleted = True
        elif denial == 'permission':
            row.access = {**row.access, 'team': True}

    boundary = ToolBoundary()
    for tool in WORK_RECORD_TOOLS:
        args = {'work_id': work['id']}
        if tool.name == 'read_work_material':
            args['material_id'] = material['id']
        call = {'name': tool.name, 'args': args, 'id': tool.name}
        request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call=call,
                                  state={'messages': [AIMessage(content='', id='model:' + tool.name, tool_calls=[call])]})

        async def read(request):
            content = await tool.coroutine(**request.tool_call['args'], runtime=request.runtime)
            return ToolMessage(content=content, tool_call_id=request.tool_call['id'], name=tool.name)

        result = await boundary.awrap_tool_call(request, read)
        assert json.loads(result.content)['state'] == 'unavailable'
        assert 'PRIVATE_CHECK_CODE' not in result.content
        await check(context)

    assert not context.read_versions and not context.document_versions and not context.document_reads
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert job.state == 'running'
        assert not job.access.get('reads')
        assert not job.result.get('workMaterialReads') and not job.result.get('documentReads')
        nodes = job.result['nodeExecution']['nodes']
        assert len(nodes) == 3 and all(node['attempts'] == 1 and not node['resumable'] for node in nodes)
        assert all(json.loads(node['output']['content'])['state'] == 'unavailable' for node in nodes)
        current = await db.get(Message, job.target_id)
        with pytest.raises(HTTPException) as caught:
            await prepare_inputs(db, users[who], job, current, settings, [{'attachment_id': material['attachment']['id']}])
        assert caught.value.status_code in (403, 404)
        unchanged = await db.get(WorkItem, work['id'])
        assert unchanged.revision == work['revision'] and unchanged.content['body'] == work['body']
        assert not (await db.get(Attachment, material['attachment']['id'])).deleted


async def test_work_tool_does_not_swallow_task_permission_loss(setup, monkeypatch):
    context, _ = await mode_runtime(setup, 'full')
    permission_error = HTTPException(403, 'task permission revoked')
    monkeypatch.setattr('app.agent.tools.business.work_records.lease', AsyncMock(side_effect=permission_error))
    for tool in WORK_RECORD_TOOLS:
        args = {'work_id': 'missing'}
        if tool.name == 'read_work_material':
            args['material_id'] = 'missing'
        with pytest.raises(HTTPException) as caught:
            await tool.coroutine(**args, runtime=SimpleNamespace(context=context))
        assert caught.value is permission_error
