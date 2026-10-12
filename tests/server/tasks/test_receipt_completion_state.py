"""Receipt shortcuts cannot turn an execution-time scope into final task status."""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agent.context.task_context import load
from app.modules.conversations.models import ConversationTaskState
from app.tasks.models import Job
from _support.agent.fakes import ReviewedFixtureModel, completion
from _support.agent.business_actions import create, runtime
from _support.agent.conversation_task_state import cancel_running
from _support.agent.response_delivery import run

pytestmark = pytest.mark.asyncio


class ReceiptScopeModel(ReviewedFixtureModel):
    work_id: str
    interpretation: dict = Field(default_factory=lambda: {
        'state': 'needs_input', 'remaining': ['此前中断的任务仍未处理'], 'relation': 'continue',
    })
    final_task: dict = Field(default_factory=lambda: {'state': 'completed', 'relation': 'continue'})
    calls: int = 0

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if isinstance(input, list) and input and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (ValueError, TypeError):
                payload = {}
            if payload.get('proposedOperation'):
                return AIMessage(content=json.dumps({
                    'allowed': True, 'quote': payload['currentUserText'], 'reason': '',
                    'receiptOnly': True, 'resumeTask': True, 'taskContext': self.interpretation,
                    'requiredFields': ['nextStep'],
                }))
        return await super().ainvoke(input, config, stop=stop, **kwargs)

    async def _agenerate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            answer = AIMessage(content='', tool_calls=[{
                'name': 'get_work_item', 'id': 'read-current', 'args': {'work_id': self.work_id},
            }])
        elif self.calls == 2:
            assert isinstance(messages[-1], ToolMessage)
            current = json.loads(messages[-1].content)
            answer = AIMessage(content='', tool_calls=[{
                'name': 'execute_business_action', 'id': 'save-next-step',
                'args': {'step': 1, 'action': 'update_work', 'target_id': self.work_id,
                         'expected_revision': current['revision'], 'changes': {'nextStep': '下周核对'}},
            }])
        else:
            assert self.calls == 3
            receipt = json.loads(messages[-1].content)
            assert receipt['state'] == 'succeeded'
            answer = completion('下一步已更新。', business=True, operation_ids=[receipt['id']], task=self.final_task)
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def interrupted_update(setup, state):
    work = await create(setup[3]['employee'], '受控恢复工作')
    first, sent = await runtime(setup, '把这项工作的下一步改成下周核对。')
    await load(first)
    if state == 'cancelled':
        await cancel_running(setup, first)
    else:
        async with setup[1].begin() as db:
            job = await db.get(Job, first.job_id)
            job.state, job.error, job.lease_until = state, '受控服务中断', None
    return work, first, sent


@pytest.mark.parametrize('previous_state', ['cancelled', 'awaiting_retry', 'failed'])
async def test_resumed_operation_finishes_without_inheriting_interrupted_placeholder(setup, previous_state):
    work, first, sent = await interrupted_update(setup, previous_state)
    fake = ReceiptScopeModel(model='controlled', api_key='unused', work_id=work['id'])
    result, stored = await run(setup, fake, '把它的下一步改成下周核对，保持同一条。',
                               conversationId=sent['conversationId'])
    assert result['job']['taskOutcome']['state'] == 'completed', result['job']['taskOutcome']
    assert result['job']['taskOutcome']['remaining'] == []
    assert result['job']['taskOutcome']['nextAction'] == 'none'
    assert fake.calls == 3 and stored.get('responseMode') != 'receipt'
    assert stored['taskSnapshot']['previousTask']['remaining'] == []
    after = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and after['nextStep'] == '下周核对'
    assert after['status'] == work['status'] and len(result['actions']) == 1
    async with setup[1]() as db:
        assert (await db.get(Job, first.job_id)).state == previous_state
        task = (await db.get(ConversationTaskState, sent['conversationId'])).payload['task']
        assert task['state'] == 'completed' and task['remaining'] == []
        assert any(source['messageId'] == sent['messageId'] for source in task['sources'])


@pytest.mark.parametrize('state,next_action', [('needs_input', 'reply'), ('blocked', 'none')])
async def test_shortcut_conflict_falls_back_without_erasing_real_remaining_requirements(setup, state, next_action):
    work, _, sent = await interrupted_update(setup, 'cancelled')
    task = {'state': state, 'remaining': ['第二项尚缺客户提供的材料'], 'relation': 'continue'}
    fake = ReceiptScopeModel(model='controlled', api_key='unused', work_id=work['id'], interpretation=task, final_task=task)
    result, stored = await run(setup, fake, '先更新下一步，再核对客户材料。', conversationId=sent['conversationId'])
    outcome = result['job']['taskOutcome']
    assert fake.calls == 3 and stored.get('responseMode') != 'receipt'
    assert outcome['state'] == 'partial' and outcome['remaining'] == task['remaining']
    assert outcome['nextAction'] == next_action


@pytest.mark.parametrize('state', ['processing', 'needs_confirmation', 'completed'])
async def test_unambiguous_single_operation_keeps_receipt_shortcut(setup, state):
    work, _, sent = await interrupted_update(setup, 'cancelled')
    fake = ReceiptScopeModel(model='controlled', api_key='unused', work_id=work['id'],
                             interpretation={'state': state, 'remaining': [], 'relation': 'continue'})
    result, stored = await run(setup, fake, '把下一步改成下周核对。', conversationId=sent['conversationId'])
    assert fake.calls == 2 and stored['responseMode'] == 'receipt'
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert result['job']['taskOutcome']['remaining'] == []
