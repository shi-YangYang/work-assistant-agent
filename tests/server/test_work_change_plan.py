"""Independent work-edit intent, patch repair and preserved record boundaries."""
import json

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import select, func

from app.agent.actions.operations import execute
from app.agent.actions.work_change_plan import WorkChangePlan, source_input, validate_plan, patch_error
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from test_business_actions import create, read_work, runtime

pytestmark = pytest.mark.asyncio


class PlanJudge:
    def __init__(self, fields):
        self.fields, self.inputs = fields, []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        assert 'proposedOperation' not in payload and 'changes' not in payload
        result = {field: {'mode': 'preserve', 'quotes': [], 'value': None} for field in ('title', 'summary', 'status', 'blocker', 'nextStep', 'dueDate')}
        for field, (mode, quote, value) in self.fields.items():
            result[field] = {'mode': mode, 'quotes': [{'messageId': payload['messageId'], 'text': quote}], 'value': value}
        return AIMessage(content=json.dumps(result))


async def test_independent_plan_blocks_missing_and_wrong_status_then_appends_once(setup, monkeypatch):
    clients = setup[3]
    work = await create(clients['employee'], '新人培训', summary='为8名新员工准备入职培训。', dueDate='2026-10-09')
    context, sent = await runtime(setup, '更新新人培训：名单已确认，但讲师时间还没定，请记成有阻碍，下一步是找讲师确认时间。')
    context.node_retry, context.intent_model = True, None
    await initialize(context, 'independent-coverage')
    await read_work(context, work['id'])
    plan = PlanJudge({'summary': ('append', '名单已确认', None), 'blocker': ('set', '讲师时间还没定', None),
                      'status': ('set', '请记成有阻碍', 'blocked'), 'nextStep': ('set', '下一步是找讲师确认时间', None)})
    calls = []
    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}, 'baseUrl': 'https://example.com'}, 'test'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    async def chat(settings, config, key, messages, *, on_event, **kwargs):
        payload = json.loads(messages[-1]['content'])
        calls.append(payload)
        await on_event('started')
        if payload.get('task') == 'work_change_plan':
            output = (await plan.ainvoke([AIMessage(content=json.dumps(payload))])).content
        else:
            assert payload['workChangePlan']['status']['value'] == 'blocked'
            output = json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '', 'requiredFields': ['summary', 'blocker', 'status', 'nextStep'],
                'requestedChanges': [{'quote': quote, 'field': field, 'kind': kind} for field, quote, kind in [('summary', '名单已确认', 'progress'), ('blocker', '讲师时间还没定', 'obstacle'), ('status', '请记成有阻碍', 'status'), ('nextStep', '下一步是找讲师确认时间', 'next_action')]],
                'appendFields': ['summary'], 'appendValues': {'summary': '名单已确认。'}})
        return {'choices': [{'message': {'role': 'assistant', 'content': output}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    changes = dict(summary='名单已确认。', blocker='讲师时间尚未确定', nextStep='找讲师确认时间')
    missing = await execute(context, **args, changes=changes)
    assert missing['category'] == 'invalid_arguments' and 'status' in missing['message']
    wrong = await execute(context, **args, changes={**changes, 'status': 'in_progress'})
    assert wrong['category'] == 'invalid_arguments' and 'blocked' in wrong['message']
    async with context.sessions() as db:
        before = await db.get(WorkItem, work['id'])
        assert before.revision == 1 and before.content['summary'] == work['summary']
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == sent['messageId'])) == 0
    changes['status'] = 'blocked'
    first = await execute(context, **args, changes=changes)
    assert first['state'] == 'succeeded'
    second = await execute(context, **args, changes=changes)
    assert second['id'] == first['id']
    after = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and after['status'] == 'blocked'
    assert after['summary'] == work['summary'] + '\n名单已确认。'
    assert after['blocker'] == changes['blocker'] and after['dueDate'] == '2026-10-09'
    assert len(calls) == 2 and len(plan.inputs) == 1  # one plan, one authorization; retries do not re-plan


async def test_plan_does_not_bypass_explicit_confirmation_or_stale_target(setup):
    from test_assistant_execution import ReceiptJudge
    from app.modules.conversations.models import Conversation
    context, sent = await runtime(setup, '仅把期限改为2026-10-11，先给我确认')
    work = await create(setup[3]['employee'], '待审工作', summary='保留说明', dueDate='2026-10-09')
    await read_work(context, work['id'])
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '期限改为2026-10-11', 'field': 'dueDate', 'kind': 'deadline'}])
    context.work_change_model = PlanJudge({'dueDate': ('set', '期限改为2026-10-11', '2026-10-11')})
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'executionMode': 'ask'}
        conversation = await db.get(Conversation, sent['conversationId'])
        conversation.execution_mode = 'ask'
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    wrong = await execute(context, **args, changes={'dueDate': '2026-10-10'})
    assert wrong['category'] == 'invalid_arguments'
    card = await execute(context, **args, changes={'dueDate': '2026-10-11'})
    assert card['state'] == 'pending'
    async with context.sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        assert row.revision == 1 and row.content['dueDate'] == '2026-10-09'
        row.revision += 1
    with pytest.raises(HTTPException) as error:
        await execute(context, **{**args, 'step': 2}, changes={'dueDate': '2026-10-12'})
    assert error.value.status_code == 409 and len(context.work_change_model.inputs) == 1


async def test_contract_preserves_unrequested_fields_and_requires_complete_original_sources():
    request = {'currentUserText': '日期改成2026-10-11', 'conversationTask': {'activeDirectives': [], 'previousTask': {'userSources': [{'messageId': 'prior', 'userText': '把下一步替换为联络客户'}]}}, 'conversationForReferenceOnly': [], 'messageTime': '2026-09-30T00:00:00+08:00', 'timezone': 'Asia/Shanghai'}
    proposal = {'targetId': 'work', 'expectedRevision': 1, 'targetContent': {'summary': '旧说明', 'status': 'blocked'}, 'changes': {'summary': '覆盖', 'status': 'done'}}
    payload = source_input(request, proposal, 'now')
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in ('title', 'summary', 'status', 'blocker', 'nextStep', 'dueDate')}
    fields['nextStep'] = {'mode': 'set', 'quotes': [{'messageId': 'prior', 'text': '下一步替换为联络客户'}], 'value': None}
    fields['dueDate'] = {'mode': 'set', 'quotes': [{'messageId': 'now', 'text': '日期改成2026-10-11'}], 'value': '2026-10-11'}
    plan = validate_plan(WorkChangePlan.model_validate(fields), payload)
    assert set(payload['targetWork']) == {'id', 'revision', 'title', 'content'}
    assert all(key in patch_error(plan, proposal) for key in ('summary', 'status', 'nextStep', 'dueDate'))
    with pytest.raises(ValueError):
        WorkChangePlan.model_validate({key: value for key, value in fields.items() if key != 'status'})
    fields['status'] = {'mode': 'set', 'quotes': [{'messageId': 'now', 'text': '已经完成'}], 'value': 'done'}
    with pytest.raises(ValueError, match='original user'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)


async def test_work_status_plan_cannot_invent_archival_state():
    payload = {'messageId': 'message', 'userSources': [{'messageId': 'message', 'userText': '归档这个工作'}]}
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in ('title', 'summary', 'status', 'blocker', 'nextStep', 'dueDate')}
    fields['status'] = {'mode': 'set', 'quotes': [{'text': '归档这个工作'}], 'value': 'archived'}
    with pytest.raises(ValueError, match='normalized'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)


@pytest.mark.parametrize('change', ['target_revision', 'cancel'])
async def test_plan_cache_respects_target_version_and_cancelled_lease(setup, change):
    from test_assistant_execution import ReceiptJudge
    from app.tasks.context import LostLease
    work = await create(setup[3]['employee'], '期限安排', dueDate='2026-10-09')
    context, _ = await runtime(setup, '期限改为2026-10-11')
    await read_work(context, work['id'])
    context.work_change_model = PlanJudge({'dueDate': ('set', '期限改为2026-10-11', '2026-10-11')})
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '期限改为2026-10-11', 'field': 'dueDate', 'kind': 'deadline'}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    assert (await execute(context, **args, changes={'dueDate': '2026-10-10'}))['category'] == 'invalid_arguments'
    async with context.sessions.begin() as db:
        if change == 'cancel':
            job = await db.get(Job, context.job_id)
            job.state = 'cancelled'
        else:
            row = await db.get(WorkItem, work['id'])
            row.content = {**row.content, 'summary': '外部补充'}
            row.revision = 2
    if change == 'cancel':
        with pytest.raises(LostLease):
            await execute(context, **args, changes={'dueDate': '2026-10-11'})
        assert len(context.work_change_model.inputs) == 1
        async with context.sessions() as db:
            assert (await db.get(WorkItem, work['id'])).revision == 1
    else:
        await read_work(context, work['id'])
        saved = await execute(context, **{**args, 'expected_revision': 2}, changes={'dueDate': '2026-10-11'})
        assert saved['state'] == 'succeeded' and saved['details']['summary'] == '外部补充'
        assert len(context.work_change_model.inputs) == 2
        assert [item['targetWork']['revision'] for item in context.work_change_model.inputs] == [1, 2]
