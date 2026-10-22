"""One authorization retry keeps its constraints, never pieces of a verdict."""
import json

import pytest
from sqlalchemy import func, select

from app.agent.actions.intent import authorize_intent
from app.agent.actions.operations import execute
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.nodes.node_state import node_dtos
from app.tasks.retry import NodeFailed
from _support.agent.business_actions import read_work, runtime
from _support.agent.conversation_task_state import close_task
from _support.agent.execution_permissions import mode_runtime
from _support.agent.task_retry import fast_nodes
from _support.materials.documents import upload
from _support.work.work_change_plan import PlanJudge

pytestmark = pytest.mark.asyncio


async def material_request(setup, monkeypatch):
    first, _ = await mode_runtime(setup, 'full', '创建材料归档工作，之后添加选中的附件')
    saved = await execute(first, step=1, action='create_work', changes={'title': '材料归档'})
    await close_task(first, state='needs_input')
    context, sent = await runtime(setup, '把选中的附件添加到材料归档工作里，保留原有内容')
    context.node_retry, context.intent_model = True, None
    await initialize(context, 'material-contract-repair')
    work = await read_work(context, saved['objectId'])
    attachment = await upload(setup[3]['employee'], '材料.txt', b'real attachment bytes', 'text/plain')
    context.work_change_model = PlanJudge({'materials': ('set', '选中的附件', None)})

    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}, 'baseUrl': 'https://example.com'}, 'test'

    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    arguments = {'step': 1, 'action': 'update_work', 'target_id': work['id'],
        'expected_revision': work['revision'], 'changes': {'materials': [{'attachmentId': attachment['id']}]}}
    return context, sent, saved, arguments


def response(payload, *, task_item='', fields=True):
    proposal = payload['proposedOperation']
    return {'allowed': True, 'quote': payload['currentUserText'], 'quoteMessageId': payload['messageId'],
        'reason': '', 'resumeTask': True, 'newTaskItem': False, 'taskItemId': task_item,
        'requiredFields': ['materials'], 'requestedChanges': [
            {'quote': '选中的附件', 'field': 'materials', 'kind': 'material'}] if fields else [],
        'materialSelection': {'mode': 'selected', 'quote': payload['currentUserText'],
            'references': proposal['changes']['materials'], 'destination': 'existing',
            'targetId': proposal['targetId'], 'destinationEvidence': {
                'source': 'user', 'messageId': payload['messageId'], 'quote': payload['currentUserText']}}}


async def install_replies(monkeypatch, context, sent, saved, replies):
    calls = []

    async def chat(settings, config, key, messages, *, on_event, **kwargs):
        payload = next(json.loads(item['content']) for item in messages
                       if item['role'] == 'user' and item['content'].startswith('{'))
        calls.append(messages)
        await on_event('started')
        # Every invalid response remains before the actual write boundary.
        async with context.sessions() as db:
            assert (await db.get(WorkItem, saved['objectId'])).revision == 1
            assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))
        task_item, fields = replies[len(calls) - 1]
        output = response(payload, task_item=saved['taskItemId'] if task_item else '', fields=fields)
        return {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(output)}, 'finish_reason': 'stop'}]}

    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    return calls


@pytest.mark.parametrize('together', [False, True])
async def test_reference_and_field_repairs_remain_joint_constraints_before_one_write(setup, monkeypatch, fast_nodes, together):
    context, sent, saved, arguments = await material_request(setup, monkeypatch)
    replies = [(True, False), (False, True)] if together else [(True, True), (False, False), (False, True)]
    calls = await install_replies(monkeypatch, context, sent, saved, replies)
    result = await execute(context, **arguments)
    assert result['state'] == 'succeeded' and len(calls) == len(replies)
    feedback = calls[-1][-1]['content']
    assert 'taskItemId' in feedback and 'requestedChanges' in feedback and 'materials' in feedback
    assert feedback.count('taskItemId') == 1 and feedback.count('requestedChanges') == 1
    assert '留空' in feedback and '不是用户缺少授权' in feedback
    # The response is evaluated as a whole, including the old task's real ID.
    assert result['taskItemId'] != saved['taskItemId']
    assert (await execute(context, **arguments))['id'] == result['id']
    assert len(calls) == len(replies)
    async with context.sessions() as db:
        work = await db.get(WorkItem, saved['objectId'])
        assert work.revision == 2
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(
            BusinessAction.message_id == sent['messageId'])) == 1
        job = await db.get(Job, context.job_id)
        authorization = next(row for row in node_dtos(job) if row['label'] == '核对操作授权中')
        assert authorization['retries'] == len(replies) - 1
        assert '本次核对输出须同时满足' not in json.dumps(job.result, ensure_ascii=False)
    shown = (await setup[3]['employee'].get('/api/v1/work-items/' + saved['objectId'])).json()
    assert len(shown['materialIds']) == 1


async def test_incomplete_alternating_verdicts_exhaust_original_budget_without_combining_grants(setup, monkeypatch, fast_nodes):
    context, sent, saved, arguments = await material_request(setup, monkeypatch)
    calls = await install_replies(monkeypatch, context, sent, saved,
                                  [(True, True), (False, False), (True, True), (False, False)])
    with pytest.raises(NodeFailed):
        await execute(context, **arguments)
    assert len(calls) == 4
    assert all('taskItemId' in messages[-1]['content'] and 'requestedChanges' in messages[-1]['content']
               for messages in calls[2:])
    assert len(calls[2][-1]['content']) == len(calls[3][-1]['content'])
    async with context.sessions() as db:
        assert (await db.get(WorkItem, saved['objectId'])).revision == 1
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))


@pytest.mark.parametrize('change', ['proposal', 'evidence', 'input'])
async def test_new_authorization_request_does_not_inherit_prior_repair_constraints(setup, monkeypatch, fast_nodes, change):
    context, _, _, _ = await material_request(setup, monkeypatch)
    # Different proposals use the same context/model path; repair input is local
    # to authorize_intent, not cached on the judge or saved with its evidence.
    calls = []

    async def chat(settings, config, key, messages, *, on_event, **kwargs):
        calls.append(messages)
        await on_event('started')
        payload = json.loads(messages[1]['content'])
        value = {'allowed': True, 'quote': payload['currentUserText'], 'reason': '',
                 'taskItemId': 'unrelated' if len(calls) == 1 else ''}
        return {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(value)}, 'finish_reason': 'stop'}]}

    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    proposal = {'action': 'create_work', 'changes': {'title': '甲'}}
    assert (await authorize_intent(context, proposal))[0]
    assert len(calls) == 2 and 'taskItemId' in calls[1][-1]['content']
    if change == 'proposal':
        proposal = {'action': 'create_work', 'changes': {'title': '乙'}}
    elif change == 'evidence':
        from types import SimpleNamespace
        from app.agent.tools.business.work import find_work_items
        await find_work_items.coroutine('', SimpleNamespace(context=context))
    else:
        await close_task(context)
        context, _ = await runtime(setup, '创建一项独立的新工作')
        context.node_retry, context.intent_model = True, None
        await initialize(context, 'another-request')
    assert (await authorize_intent(context, proposal))[0]
    assert len(calls) == 3 and len(calls[2]) == 2
    assert calls[2][-1]['content'].startswith('{')


async def test_schema_field_repairs_accumulate_without_echoing_values(setup, monkeypatch, fast_nodes):
    context, sent, saved, _ = await material_request(setup, monkeypatch)
    calls = []
    secret = 'not part of repair feedback'

    async def chat(settings, config, key, messages, *, on_event, **kwargs):
        calls.append(messages)
        await on_event('started')
        payload = json.loads(messages[1]['content'])
        value = {'allowed': True, 'quote': payload['currentUserText'], 'reason': ''}
        if len(calls) == 1:
            value['quote'] = [secret]
        elif len(calls) == 2:
            value['requiredFields'] = secret
        return {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(value)}, 'finish_reason': 'stop'}]}

    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    assert (await authorize_intent(context, {'action': 'create_work', 'changes': {'title': '甲'}}))[0]
    assert len(calls) == 3
    assert 'quote: string_type' in calls[2][-1]['content']
    assert 'requiredFields: list_type' in calls[2][-1]['content']
    assert secret not in calls[2][-1]['content']
    async with context.sessions() as db:
        assert (await db.get(WorkItem, saved['objectId'])).revision == 1
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))


@pytest.mark.parametrize('final_missing', [False, True])
async def test_invalid_response_does_not_publish_field_diagnostics_from_its_partial_verdict(setup, monkeypatch, fast_nodes, final_missing):
    from app.core.digests import digest
    context, _, saved, _ = await material_request(setup, monkeypatch)
    proposal = {'action': 'edit_report', 'changes': {'completed': '已完成整理'}}
    calls = []

    async def chat(settings, config, key, messages, *, on_event, **kwargs):
        calls.append(messages)
        await on_event('started')
        assert digest(proposal) not in context.authorization_details
        payload = json.loads(messages[1]['content'])
        fields = ['completed', 'ongoing'] if len(calls) == 1 or final_missing else ['completed']
        value = {'allowed': True, 'quote': payload['currentUserText'], 'reason': '',
                 'taskItemId': saved['taskItemId'] if len(calls) == 1 else '', 'requiredFields': fields,
                 'requestedChanges': [{'field': field, 'quote': payload['currentUserText']} for field in fields]}
        return {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(value)}, 'finish_reason': 'stop'}]}

    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    assert (await authorize_intent(context, proposal))[0] is not final_missing
    assert len(calls) == 2
    if final_missing:
        assert context.authorization_details[digest(proposal)] == [{'field': 'ongoing', 'code': 'missing'}]
    else:
        assert digest(proposal) not in context.authorization_details
