"""Commit-window recovery: dedicated DB, fixed judges, no provider requests."""
import json
from datetime import timedelta
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import func, select
from app.agent import operations
from app.agent.tool_nodes import tool_node
from app.agent.tools.actions import query_reports
from app.db.base import now
from app.integrations.models.transport import ProviderError
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem
from app.tasks import node_execution
from app.tasks.context import InputChanged, LostLease, RunContext
from app.tasks.models import Job
from app.tasks.node_state import execution
from app.tasks.queue import claim
from test_business_actions import Judge, create, read_work
from test_task_retry import enabled, fast_nodes

pytestmark = pytest.mark.asyncio


class ProcessStopped(BaseException):
    def __init__(self, result):
        self.result = result


async def interrupted_node(setup, monkeypatch, action):
    context, _ = await enabled(setup)
    args = {'step': 1, 'action': action}
    target_id = None
    if action in ('update_work', 'delete_work', 'generate_report'):
        work = await create(setup[3]['employee'])
        if action != 'generate_report':
            target_id = work['id']
            await node_execution.execute_node(context, identity='read', kind='tool', label='读取工作',
                                              operation=lambda: read_work(context, target_id))
    elif action in ('edit_report', 'submit_report', 'delete_report'):
        async with context.sessions.begin() as db:
            report = Report(company_id=context.company_id, owner_id=context.owner_id, kind='daily',
                            period=now().date().isoformat(), period_end=now().date().isoformat(),
                            timezone='Asia/Shanghai', content={'ongoing': '正在整理方案'})
            db.add(report)
            await db.flush()
            target_id = report.id
        await node_execution.execute_node(context, identity='read', kind='tool', label='读取报告',
                                          operation=lambda: query_reports.coroutine(SimpleNamespace(context=context), report_id=target_id))
    if target_id:
        args.update(target_id=target_id, expected_revision=1)
    if action == 'update_work':
        args['changes'] = {'summary': '已整理方案'}
    elif action == 'edit_report':
        args['changes'] = {'ongoing': '方案整理中'}
    elif action == 'create_work':
        args['changes'] = {'title': '报价方案'}
    elif action == 'generate_report':
        args['report_date'] = now().date().isoformat()
    call = {'name': 'execute_business_action', 'id': 'write', 'args': args}
    request = SimpleNamespace(tool_call=call, state={'messages': [AIMessage(id='batch', content='', tool_calls=[call])]})
    execute_once = operations._execute
    async def stop_after_commit(context, **arguments):
        result = await execute_once(context, **arguments)
        # _execute's transaction has committed, but execute.remember, the tool
        # response and node output/read-version journal have not run.
        raise ProcessStopped(result)
    monkeypatch.setattr(operations, '_execute', stop_after_commit)
    calls = []
    async def write():
        calls.append(True)
        if len(calls) < 4:
            raise ProviderError('network', 'controlled pre-write failure')
        result = await operations.execute(context, **args)
        return ToolMessage(content=json.dumps(result), tool_call_id=call['id'], name=call['name'])
    with pytest.raises(ProcessStopped) as stopped:
        await tool_node(context, request, write)
    assert len(calls) == 4
    assert stopped.value.result['state'] in ('succeeded', 'pending', 'running')
    assert len(context.intent_model.inputs) == 1
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        state = execution(job)
        row = next(item for item in state['nodes'] if item.get('receiptId'))
        assert row['state'] == 'running' and row['attempts'] == 4 and 'output' not in row
        assert row['receiptId'] == stopped.value.result['id']
        if target_id:
            assert state['readVersions'][target_id] == 1
        job.lease_until = now() - timedelta(seconds=1)
    claimed = await claim(context.sessions, context.owner_id)
    assert claimed.id == context.job_id and claimed.fence > context.fence
    recovered = RunContext(claimed.owner_id, claimed.company_id, claimed.id, claimed.fence,
                           context.sessions, context.settings, source_revision=0, intent_model=Judge(), node_retry=True)
    await node_execution.initialize(recovered, 'fixed-input')
    return recovered, request, stopped.value.result


async def forbidden():
    raise AssertionError('A committed business operation must not execute again')


@pytest.mark.parametrize('action', ['create_work', 'update_work', 'edit_report', 'generate_report',
                                   'delete_work', 'submit_report', 'delete_report'])
async def test_fourth_attempt_committed_receipt_recovers_without_reexecution(setup, fast_nodes, monkeypatch, action):
    context, request, committed = await interrupted_node(setup, monkeypatch, action)
    result = json.loads((await tool_node(context, request, forbidden)).content)
    assert result == committed
    assert context.intent_model.inputs == []
    if action in ('update_work', 'edit_report'):
        assert result['objectRevision'] == 2
        assert context.read_versions[result['objectId']] == 2
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        state = execution(job)
        row = next(item for item in state['nodes'] if item.get('receiptId'))
        assert row['state'] == ('awaiting_confirmation' if committed['state'] == 'pending' else 'succeeded')
        assert row['attempts'] == 4 and row['totalRetries'] == 3 and row['output']
        assert state.get('readVersions', {}) == context.read_versions
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == job.target_id)) == 1
        if action == 'generate_report':
            assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == context.owner_id, Job.kind == 'report')) == 1


@pytest.mark.parametrize('action', ['update_work', 'edit_report'])
@pytest.mark.parametrize('change', ['revision', 'deleted'])
async def test_receipt_recovery_rejects_external_target_changes(setup, fast_nodes, monkeypatch, action, change):
    context, request, committed = await interrupted_node(setup, monkeypatch, action)
    async with context.sessions.begin() as db:
        target = await db.get(WorkItem if action == 'update_work' else Report, committed['objectId'])
        if change == 'revision':
            target.revision += 1
        else:
            target.deleted = True
    with pytest.raises(ProviderError) as error:
        await tool_node(context, request, forbidden)
    assert error.value.code == 'version_conflict'
    assert context.intent_model.inputs == []
    assert context.read_versions[committed['objectId']] == 1


@pytest.mark.parametrize('change', ['permission', 'input', 'config', 'other_read'])
async def test_receipt_recovery_keeps_authorization_input_config_and_other_reads(setup, fast_nodes, monkeypatch, change):
    context, request, _ = await interrupted_node(setup, monkeypatch, 'update_work')
    async with context.sessions.begin() as db:
        if change == 'permission':
            (await db.get(Member, context.owner_id)).active = False
        elif change == 'input':
            job = await db.get(Job, context.job_id)
            (await db.get(Message, job.target_id)).transcript_revision += 1
    if change == 'config':
        context.model_binding = {'assistant': {'model': 'controlled'}}
        async def revoked(*args):
            raise ProviderError('revoked', '配置已撤销')
        monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', revoked)
    elif change == 'other_read':
        other = await create(setup[3]['employee'], title='另一项工作')
        context.read_versions[other['id']] = 1
        async with context.sessions.begin() as db:
            (await db.get(WorkItem, other['id'])).revision += 1
    expected = LostLease if change == 'permission' else InputChanged if change == 'input' else ProviderError
    with pytest.raises(expected):
        await tool_node(context, request, forbidden)
    assert context.intent_model.inputs == []
