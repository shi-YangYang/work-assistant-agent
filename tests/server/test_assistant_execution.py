"""Execution shortcuts and live receipts must keep the existing trust boundaries."""
import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from fakes import completion
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.agent.completion.completion import receipt_completion
from app.agent.harness import invoke_harness
from app.agent.actions.operations import execute
from app.agent.tools.team import query_team_business
from app.core.digests import digest
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.tasks.models import Job
from pydantic import Field
from test_business_actions import Judge, create, read_work, runtime
from types import SimpleNamespace



pytestmark = pytest.mark.asyncio


class ReceiptJudge(Judge):
    def __init__(self, *, receipt=True, allowed=True, required_fields=(), requested_changes=()):
        super().__init__(allowed)
        self.receipt = receipt
        self.required_fields = required_fields
        self.requested_changes = requested_changes

    async def ainvoke(self, messages):
        response = await super().ainvoke(messages)
        verdict = json.loads(response.content)
        if 'allowed' in verdict:
            verdict['receiptOnly'] = self.receipt
            verdict['requiredFields'] = list(self.required_fields)
            verdict['requestedChanges'] = list(self.requested_changes)
        return AIMessage(content=json.dumps(verdict))


class SingleOperation(ChatOpenAI):
    calls: list = Field(default_factory=list)

    async def _agenerate(self, messages, **kwargs):
        self.calls.append(True)
        if isinstance(messages[-1], ToolMessage):
            answer = completion('操作之外仍需要回答的问题。', business=True)
        else:
            answer = AIMessage(content='', tool_calls=[{'name': 'execute_business_action', 'id': 'save', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '报价方案'}}}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.mark.parametrize('receipt', [True, False])
async def test_operation_only_shortcuts_generation_and_survives_checkpoint_resume(setup, receipt):
    settings, sessions, _, c = setup
    context, sent = await runtime(setup, '帮我创建工作：报价方案' if receipt else '帮我创建工作：报价方案，并给我建议')
    context.intent_model = ReceiptJudge(receipt=receipt)
    model = SingleOperation(model='controlled', api_key='unused')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        answer = await invoke_harness(context, saver, '按当前请求执行', model)
        assert len(model.calls) == (1 if receipt else 2)
        assert (answer == '') is receipt
        again = await invoke_harness(context, saver, '按当前请求执行', model)
        assert again == answer and len(model.calls) == (1 if receipt else 2)
    detail = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(detail['actions']) == 1 and detail['actions'][0]['state'] == 'succeeded'
    async with sessions() as db:
        live = await db.get(Job, context.job_id)
        assert (live.result.get('responseMode') == 'receipt') is receipt


def returned(receipt, *, extra=False):
    calls = [{'name': 'execute_business_action', 'id': 'save', 'args': {}}]
    if extra:
        calls.append({'name': 'find_work_items', 'id': 'query', 'args': {'query': ''}})
    return [AIMessage(content='', tool_calls=calls), ToolMessage(name='execute_business_action', tool_call_id='save', content=json.dumps(receipt))]


async def test_shortcut_cannot_be_claimed_by_tool_text_or_skip_parallel_steps(setup):
    _, sessions, _, _ = setup
    context, _ = await runtime(setup)
    card = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    assert not await receipt_completion(context, returned({**card, 'receiptOnly': True}))
    async with sessions.begin() as db:
        row = await db.get(BusinessAction, card['id'])
        row.result = {**row.result, 'receiptOnly': True, 'receiptInput': digest({'text': '帮我创建工作：报价方案', 'sourceRevision': 0, 'documents': {}})}
    assert not await receipt_completion(context, returned(card, extra=True))
    assert not await receipt_completion(context, returned({**card, 'id': 'made-up'}))
    assert await receipt_completion(context, returned(card))
    await execute(context, step=2, action='create_work', changes={'title': '第二项'})
    assert not await receipt_completion(context, returned(card))


async def test_failed_intent_never_activates_shortcut(setup):
    context, _ = await runtime(setup, '不要创建')
    context.intent_model = ReceiptJudge(allowed=False)
    card = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    assert card['state'] == 'clarification' and not context.receipt_candidates
    assert not await receipt_completion(context, returned(card))


@pytest.mark.parametrize('missing', [('status', 'summary'), ('blocker',), ('nextStep',)])
async def test_partial_update_cannot_write_or_shortcut_before_all_requested_fields_are_present(setup, missing):
    _, sessions, _, clients = setup
    work = await create(clients['employee'], '客户培训', summary='准备培训材料')
    context, sent = await runtime(setup, '客户培训改为有阻碍，说明补充8人名单已确认，阻碍是讲师时间未定，下一步联系讲师。')
    changes = {'status': 'blocked', 'summary': '准备培训材料\n8人名单已确认', 'blocker': '讲师时间未定', 'nextStep': '联系讲师'}
    context.intent_model = ReceiptJudge(required_fields=changes)
    await read_work(context, work['id'])
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1}
    rejected = await execute(context, **args, changes={key: value for key, value in changes.items() if key not in missing})
    assert rejected['state'] == 'clarification' and rejected['category'] == 'invalid_arguments'
    assert all(field in rejected['message'] for field in missing)
    assert not context.receipt_candidates
    before = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert before['revision'] == 1 and before['status'] == 'in_progress' and before['summary'] == '准备培训材料'
    assert not (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['actions']
    saved = await execute(context, **args, changes=changes)
    assert saved['state'] == 'succeeded' and await receipt_completion(context, returned(saved))
    after = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and all(after[key] == value for key, value in changes.items())
    assert await execute(context, **args, changes=changes) == saved
    assert len(context.intent_model.inputs) == 2


async def test_corrected_input_cannot_reuse_prior_completion_decision(setup):
    _, sessions, _, _ = setup
    context, sent = await runtime(setup)
    context.intent_model = ReceiptJudge()
    card = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    assert await receipt_completion(context, returned(card))
    async with sessions.begin() as db:
        message = await db.get(Message, sent['messageId'])
        message.transcript_revision = 1
        message.transcript = '还需要说明报价依据'
    context.source_revision = 1
    from app.tasks.context import InputChanged
    with pytest.raises(InputChanged):
        await receipt_completion(context, returned(card))


async def test_original_progress_fact_blocks_partial_update_even_if_field_summary_omits_it(setup):
    _, _, _, clients = setup
    work = await create(clients['employee'], '验收交付', summary='准备验收')
    context, sent = await runtime(setup, '更新验收交付：联调已通过，但客户验收时间未定，记为有阻碍，下一步联系客户。')
    context.intent_model = ReceiptJudge(required_fields=['status', 'blocker', 'nextStep'], requested_changes=[
        {'quote': '联调已通过', 'field': 'summary'},
        {'quote': '客户验收时间未定', 'field': 'blocker'},
        {'quote': '记为有阻碍', 'field': 'status'},
        {'quote': '下一步联系客户', 'field': 'nextStep'},
    ])
    await read_work(context, work['id'])
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1}
    changes = {'status': 'blocked', 'blocker': '客户验收时间未定', 'nextStep': '联系客户'}
    refused = await execute(context, **args, changes=changes)
    assert refused['category'] == 'invalid_arguments' and 'summary' in refused['message']
    unchanged = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert unchanged['revision'] == 1 and unchanged['summary'] == '准备验收' and unchanged['status'] == 'in_progress'
    assert not (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['actions']
    assert not context.receipt_candidates
    saved = await execute(context, **args, changes={**changes, 'summary': '准备验收；联调已通过'})
    after = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['state'] == 'succeeded' and after['revision'] == 2
    assert after['summary'] == '准备验收；联调已通过' and after['status'] == 'blocked'
    assert after['blocker'] == changes['blocker'] and after['nextStep'] == changes['nextStep']


async def test_coverage_quotes_cannot_invent_progress_or_borrow_unrelated_history():
    from app.agent.actions.intent import IntentVerdict, requested_change_contract
    verdict = IntentVerdict(allowed=True, quote='更新验收', reason='', requestedChanges=[{'quote': '联调已通过', 'field': 'summary'}])
    task = {'previousTask': {'userSources': [{'userText': '联调已通过'}]}}
    assert not requested_change_contract(verdict, '更新验收：联系客户', task)
    assert requested_change_contract(verdict, '更新验收：联调已通过', task)
    assert requested_change_contract(verdict.model_copy(update={'resumeTask': True}), '继续上次更新', task)


async def test_live_receipts_arrive_before_completion_and_revalidate_confirmation(setup):
    _, sessions, _, c = setup
    work = await create(c['employee'])
    context, sent = await runtime(setup, '删除报价方案')
    context.intent_model = ReceiptJudge()
    await read_work(context, work['id'])
    card = await execute(context, step=1, action='delete_work', target_id=work['id'], expected_revision=1)
    feedback = (await c['employee'].get(f'/api/v1/jobs/{context.job_id}/feedback')).json()
    assert feedback['state'] == 'running' and feedback['stage'] == 'operating'
    assert feedback['actions'] == [card] and card['state'] == 'pending'
    assert await receipt_completion(context, returned(card))
    for role in ('peer', 'admin', 'outsider'):
        assert (await c[role].get(f'/api/v1/jobs/{context.job_id}/feedback')).status_code == 404
    result = await c['employee'].post('/api/v1/work-items/' + work['id'] + '/progress', json={'expectedRevision': 1, 'title': '报价方案', 'summary': '用户已更新'})
    assert result.status_code == 200
    assert not await receipt_completion(context, returned(card))
    changed = (await c['employee'].get(f'/api/v1/jobs/{context.job_id}/feedback')).json()
    assert changed['actions'][0]['state'] == 'conflict' and not changed['actions'][0].get('canConfirm')
    assert (await c['employee'].get('/api/v1/work-items/' + work['id'])).status_code == 200


async def test_named_team_query_resolves_once_without_widening_scope(setup):
    _, sessions, users, c = setup
    await create(c['employee'], '甲的工作')
    await create(c['peer'], '乙的工作')
    context, _ = await runtime(setup, '查询员工工作', 'admin')
    rt = SimpleNamespace(context=context)
    result = json.loads(await query_team_business.coroutine(rt, employee_name=users['employee'].name))
    assert result['total'] == 1 and result['items'][0]['title'] == '甲的工作'
    assert result['employee']['id'] == users['employee'].id
    assert result['items'][0]['token']
    assert 'error' in json.loads(await query_team_business.coroutine(rt, employee_name=users['employee'].name, employee_ids=[users['peer'].id]))
    missing = json.loads(await query_team_business.coroutine(rt, employee_name='没有这个人'))
    assert missing['state'] == 'not_found' and 'items' not in missing
    async with sessions.begin() as db:
        peer = await db.get(Member, users['peer'].id)
        peer.name = users['employee'].name
    ambiguous = json.loads(await query_team_business.coroutine(rt, employee_name=users['employee'].name))
    assert ambiguous['state'] == 'clarification' and ambiguous['members']['total'] == 2
    assert 'items' not in ambiguous
    employee_context, _ = await runtime(setup)
    denied = json.loads(await query_team_business.coroutine(SimpleNamespace(context=employee_context), employee_name=users['employee'].name))
    assert 'error' in denied
