"""Report receipts survive the actual harness input and selective history cache."""
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Field

from app.agent.actions.interactions import finish_waiting
from app.agent.actions.operations import execute
from app.agent.context.references.conversation_context import conversation_references
from app.agent.harness import invoke_harness
from app.agent.tools.business.actions import query_reports
from app.db.base import now
from app.modules.conversations.models import ConversationContext
from app.modules.messages.models import Message
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import Judge, create, finish
from _support.agent.execution_permissions import mode_runtime, set_mode
from _support.agent.fakes import ReviewedFixtureModel, completion
from _support.http.company import keyed
from _support.work.report_reliability import CONTENT, ReportModel

pytestmark = pytest.mark.asyncio


async def generated_report(setup):
    settings, sessions, users, clients = setup
    await create(clients['employee'], title='方案', summary='方案初稿已完成', status='done')
    previous, sent = await mode_runtime(setup, 'full', '根据已有工作生成本周周报草稿，不提交')
    card = await execute(previous, step=1, action='generate_report', report_kind='weekly',
                         report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    assert card['state'] == 'running'
    await finish(previous)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    return sent, card


async def following_turn(setup, conversation_id, text):
    settings, sessions, users, clients = setup
    response = await clients['employee'].post('/api/v1/messages',
        json={'conversationId': conversation_id, 'text': text}, headers=keyed())
    assert response.status_code == 202, response.text
    job = await claim(sessions, users['employee'].id)
    assert job.id == response.json()['jobId']
    return RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings,
                      source_revision=0, intent_model=Judge()), response.json()


class CapturingModel(ReviewedFixtureModel):
    requests: list = Field(default_factory=list)

    async def _agenerate(self, messages, **kwargs):
        self.requests.append(messages)
        return ChatResult(generations=[ChatGeneration(message=completion('已按回执核对。'))])


@pytest.mark.parametrize('submit', [False, True])
async def test_report_snapshot_reaches_actual_model_after_generation_and_approval(setup, submit):
    settings, sessions, users, clients = setup
    generated, card = await generated_report(setup)
    if submit:
        await set_mode(clients['employee'], 'auto')
        pending_context, pending = await following_turn(setup, generated['conversationId'], '提交刚才的周报')
        result = json.loads(await query_reports.coroutine(SimpleNamespace(context=pending_context), report_id=card['objectId']))
        receipt = await execute(pending_context, step=1, action='submit_report', target_id=card['objectId'],
                                expected_revision=result['items'][0]['revision'])
        assert receipt['state'] == 'pending'
        await finish_waiting(pending_context)
        confirmed = await clients['employee'].post('/api/v1/business-actions/' + receipt['id'] + '/confirm',
                                                   json={'expectedRevision': receipt['revision']})
        assert confirmed.status_code == 200, confirmed.text
        followup = confirmed.json()['continuation']
        job = await claim(sessions, users['employee'].id)
        assert job.id == followup['jobId']
        context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings,
                             source_revision=0, intent_model=Judge())
        target_message = pending['messageId']
    else:
        context, _ = await following_turn(setup, generated['conversationId'], '刚才保存的草稿有哪些内容？')
        target_message = generated['messageId']
    model = CapturingModel(model='controlled-input-only', api_key='no-network')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await invoke_harness(context, saver, '请按当前回执回答。', model)
    assert len(model.requests) == 1  # Projection adds no model verification round.
    reply = next(message for message in model.requests[0] if message.id == 'history-reply:' + target_message)
    projected = json.loads(reply.content.split('（历史方案不代表已执行）：', 1)[1])
    evidence = projected[0]['reportSnapshot']
    assert projected[0]['state'] == 'succeeded'
    assert projected[0]['action'] == ('submit_report' if submit else 'generate_report')
    assert evidence['content'] == CONTENT and evidence['emptyFields'] == ['blockers']
    assert evidence['source'] == 'business_action_receipt' and evidence['status'] == 'saved'
    assert evidence['revision'] == projected[0]['objectRevision']
    assert bool(evidence['publishedRevision']) is submit
    await finish(context)


@pytest.mark.parametrize('summarized', [False, True])
async def test_old_report_projection_rebuilds_once_without_rebuilding_ordinary_history(setup, monkeypatch, summarized):
    settings, sessions, users, clients = setup
    generated, card = await generated_report(setup)
    neutral, neutral_sent = await following_turn(setup, generated['conversationId'], '谢谢')
    await finish(neutral)
    current_context, current_sent = await following_turn(setup, generated['conversationId'], '刚才的报告保存了什么？')
    actor = users['employee']
    async with sessions.begin() as db:
        job = await db.get(Job, current_context.job_id)
        current = await db.get(Message, current_sent['messageId'])
        await conversation_references(db, actor, job, current)
        store = await db.get(ConversationContext, generated['conversationId'])
        payload = json.loads(json.dumps(store.payload))
        if summarized:
            # An old compressed summary must not hide the newly available
            # report evidence. Only result stamps change, not source validity.
            payload['summary'] = '此前报告已提交，风险四条均已包含。'
            payload['sources'][generated['messageId']] = {**payload['sources'][generated['messageId']], 'result': 'old-receipt-projection'}
            payload['summarySources'] = {generated['messageId']: payload['sources'][generated['messageId']]}
            payload['recentMessages'] = [row for row in payload['recentMessages'] if row['id'] != generated['messageId']]
        else:
            for reference in payload['recentMessages']:
                for action in reference['currentActions']:
                    action.pop('reportSnapshot', None)
        store.payload = payload
    from app.modules.conversations import references as module
    original, rebuilt = module.message_reference, []
    async def tracked(db, actor, message, **kwargs):
        rebuilt.append(message.id)
        return await original(db, actor, message, **kwargs)
    monkeypatch.setattr(module, 'message_reference', tracked)
    for _ in range(2):
        async with sessions.begin() as db:
            current = await db.get(Message, current_sent['messageId'])
            job = await db.get(Job, current_context.job_id)
            refs = await conversation_references(db, actor, job, current)
            report = next(row for row in refs if row['id'] == generated['messageId'])
            assert report['currentActions'][0]['reportSnapshot']['emptyFields'] == ['blockers']
            assert any(row['id'] == neutral_sent['messageId'] for row in refs)
    assert rebuilt == [generated['messageId']]
    await finish(current_context)
