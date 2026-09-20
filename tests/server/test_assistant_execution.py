"""Execution shortcuts and live receipts must keep the existing trust boundaries."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Field

from paa_server.agent.completion import receipt_completion
from paa_server.agent.harness import invoke_harness, query_team_business
from paa_server.business_actions import digest, execute
from paa_server.models import BusinessAction, Job, Member, Message
from test_business_actions import Judge, create, read_work, runtime

pytestmark = pytest.mark.asyncio


class ReceiptJudge(Judge):
    def __init__(self, *, receipt=True, allowed=True):
        super().__init__(allowed)
        self.receipt = receipt

    async def ainvoke(self, messages):
        response = await super().ainvoke(messages)
        verdict = json.loads(response.content)
        if 'allowed' in verdict:
            verdict['receiptOnly'] = self.receipt
        return AIMessage(content=json.dumps(verdict))


class SingleOperation(ChatOpenAI):
    calls: list = Field(default_factory=list)

    async def _agenerate(self, messages, **kwargs):
        self.calls.append(True)
        if isinstance(messages[-1], ToolMessage):
            answer = AIMessage(content='操作之外仍需要回答的问题。')
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
    assert not await receipt_completion(context, returned(card))


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
