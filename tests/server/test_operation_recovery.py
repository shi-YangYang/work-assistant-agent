"""Conversation continuity, retry boundaries and explicit voice instructions."""
import json
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.agent.history import conversation_history
from app.agent.intent import authorize_intent
from app.agent.operations import execute
from app.agent.policies import action_policy
from app.agent.tools.messages import get_message_context
from app.agent.tools.work import find_work_items
from app.modules.attachments.models import Attachment
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem
from app.tasks.handlers import process_job
from app.tasks.models import Job
from app.tasks.queue import claim
from sqlalchemy import func, select
from test_business_actions import Judge, ReplyJudge, create, finish, read_work, run_reply, runtime
from test_company import keyed
from types import SimpleNamespace
from unittest.mock import AsyncMock



pytestmark = pytest.mark.asyncio


async def test_intent_and_reasoning_share_referenced_plan_outside_recent_window(setup):
    _, sessions, _, c = setup
    work = await create(c['employee'], title='旧工作')
    prior, sent = await runtime(setup, '请给这个工作一个测试模板方案，标题、摘要和下一步都改，阻碍清空。')
    plan = '|标题|测试模板|\n|摘要|测试用摘要|\n|下一步|执行测试|\n|阻碍|清空|'
    async with sessions.begin() as db:
        message = await db.get(Message, sent['messageId'])
        message.reply = plan
    await finish(prior)
    for index in range(13):
        intermediate, _ = await runtime(setup, f'其他讨论{index}')
        await finish(intermediate)
    response = await c['employee'].post('/api/v1/messages', json={'text': '按上表改，状态和日期不变。', 'replyTo': sent['messageId']}, headers=keyed())
    assert response.status_code == 202
    from app.tasks.context import RunContext
    job = await claim(sessions, prior.owner_id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, prior.settings, source_revision=0, intent_model=Judge())
    history = '\n'.join(str(m.content) for m in await conversation_history(context, job, '按上表改'))
    assert plan in history
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'title': '测试模板', 'summary': '测试用摘要', 'nextStep': '执行测试', 'blocker': ''})
    references = context.intent_model.inputs[-1]['conversationForReferenceOnly']
    parent = next(row for row in references if row['id'] == sent['messageId'])
    assert parent['assistantReference'] == plan and parent['explicitReplyTarget']
    assert '状态和日期不变' in context.intent_model.inputs[-1]['currentUserText']
    assert result['state'] == 'succeeded'
    assert result['details']['status'] == 'in_progress' and result['details']['dueDate'] is None
    assert 'blocker' in result['changedFields']


async def test_saved_action_preserves_independent_followup_plan_in_history_and_tool(setup):
    _, sessions, _, _ = setup
    async def saved(context):
        await execute(context, step=1, action='create_work', changes={'title': '测试工作'})
    plan = '方案一：摘要使用测试内容；方案二：只改标题。'
    result = await run_reply(setup, '创建测试工作，然后给我两个改写方案', plan, ReplyJudge(['information']), before=saved)
    context, _ = await runtime(setup, '选择方案一，帮我拟写测试内容。')
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
    history = '\n'.join(str(m.content) for m in await conversation_history(context, job, '方案一'))
    assert plan in history and 'succeeded' in history
    source = json.loads(await get_message_context.coroutine(result['id'], SimpleNamespace(context=context)))
    assert source['reply'] == plan and source['currentActions'][0]['state'] == 'succeeded'
    await authorize_intent(context, {'action': 'update_work'})
    assert plan in json.dumps(context.intent_model.inputs[-1], ensure_ascii=False)


@pytest.mark.parametrize('field', ['title', 'summary', 'blocker', 'nextStep'])
async def test_assistant_search_matches_page_including_literal_wildcards(setup, field):
    _, _, _, c = setup
    await create(c['employee'], **{'title': '方案', field: '定位值100%_测试'})
    context, _ = await runtime(setup, '查询定位值100%_测试')
    page = (await c['employee'].get('/api/v1/work-items', params={'q': '100%_'})).json()
    found = json.loads(await find_work_items.coroutine('100%_', SimpleNamespace(context=context)))
    assert len(found['items']) == 1
    assert [row['id'] for row in found['items']] == [row['id'] for row in page['items']]
    no_match = json.loads(await find_work_items.coroutine('100x_', SimpleNamespace(context=context)))
    assert no_match['items'] == []


async def test_clarification_and_conflicts_survive_response_failure(setup):
    _, _, _, c = setup
    work = await create(c['employee'])
    context, sent = await runtime(setup, '改成之前提到的那种', allowed=False)
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'title': '猜的标题'})
    detail = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['state'] == 'clarification' and not detail['actions']
    assert detail['job']['operationFeedback'][0]['message'] == result['message']
    context.intent_model = Judge()
    applied = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'title': '确定标题'})
    assert applied['state'] == 'succeeded'
    detail = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['operationFeedback'] == []
    assert (await c['peer'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404


async def test_retry_replaces_failed_response_in_place_without_repeating_business(setup, monkeypatch):
    settings, sessions, users, c = setup
    async def saved(context):
        await execute(context, step=1, action='create_work', changes={'title': '只创建一次'})
    result = await run_reply(setup, '帮我创建工作，然后给建议', '下一步可以检查需求。', ReplyJudge(['information'], fail=True), before=saved)
    assert result['job']['state'] == 'awaiting_retry'
    async with sessions() as db:
        job = await db.get(Job, result['job']['id'])
        assert job.result['replyReviewError'] == 'BudgetExceeded'
    retry = await c['employee'].post('/api/v1/jobs/' + result['job']['id'] + '/retry', json={})
    assert retry.status_code == 200
    assert retry.json()['state'] == 'queued' and retry.json()['error'] == ''
    queued = (await c['employee'].get('/api/v1/messages/' + result['id'])).json()
    assert queued['text'] == result['text'] and queued['reply'] == ''
    assert queued['citations'] == [] and queued['businessCitations'] == []
    assert queued['actions'][0]['id'] == result['actions'][0]['id']
    assert (await c['employee'].post('/api/v1/jobs/' + result['job']['id'] + '/retry', json={})).status_code == 409
    graph = AsyncMock(side_effect=AssertionError('review retry must not run the graph'))
    monkeypatch.setattr('app.tasks.handlers.invoke_harness', graph)
    job = await claim(sessions, users['employee'].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=object(), reply_model=ReplyJudge(['information']))
    detail = (await c['employee'].get('/api/v1/messages/' + result['id'])).json()
    assert detail['job']['state'] == 'succeeded', detail
    assert '下一步可以检查需求' in detail['reply']
    assert detail['actions'][0]['id'] == result['actions'][0]['id']
    graph.assert_not_awaited()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 1
        assert await db.scalar(select(func.count()).select_from(Message).where(Message.owner_id == users['employee'].id)) == 1
        assert 'pendingReply' not in (await db.get(Job, job.id)).result


async def test_voice_instruction_requires_explicit_attached_audio_choice(setup):
    _, sessions, users, c = setup
    from app.tasks.context import RunContext
    actor = users['employee']
    async with sessions.begin() as db:
        audio = Attachment(company_id=actor.company_id, owner_id=actor.id, kind='audio', mime='audio/wav', name='voice.wav', size=100, sha256='a' * 64)
        image = Attachment(company_id=actor.company_id, owner_id=actor.id, kind='image', mime='image/png', name='image.png', size=100, sha256='a' * 64)
        db.add_all([audio, image]); await db.flush()
    invalid = await c['employee'].post('/api/v1/messages', json={'attachmentIds': [image.id], 'voiceCommandAttachmentId': image.id}, headers=keyed())
    assert invalid.status_code == 422
    body = {'attachmentIds': [audio.id], 'voiceCommandAttachmentId': audio.id}
    headers = keyed()
    response = await c['employee'].post('/api/v1/messages', json=body, headers=headers)
    assert response.status_code == 202, response.text
    assert (await c['employee'].post('/api/v1/messages', json=body, headers=headers)).json() == response.json()
    async with sessions.begin() as db:
        message = await db.get(Message, response.json()['messageId'])
        message.transcript = '帮我创建一个工作：整理材料'
        message.transcript_revision = 1
    job = await claim(sessions, actor.id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, setup[0], source_revision=1, intent_model=Judge())
    assert (await execute(context, step=1, action='create_work', changes={'title': '整理材料'}))['state'] == 'succeeded'
    assert context.intent_model.inputs[0]['currentUserText'] == message.transcript
    source = json.loads(await get_message_context.coroutine(message.id, SimpleNamespace(context=context)))
    assert source['transcript'] == message.transcript and source['userRequest'] == message.transcript
    assert source['text'] == ''
    # Removing explicit origin leaves identical audio as material, never a command.
    async with sessions.begin() as db:
        live = await db.get(Job, job.id)
        live.result = {k: v for k, v in live.result.items() if k != 'voiceCommandAttachmentId'}
    assert not (await authorize_intent(context, {'action': 'create_work'}))[0]


async def test_role_capabilities_do_not_advertise_admin_personal_reports(setup):
    assert '没有管理员个人日报周报' in action_policy('admin')
    assert '不能删除已提交报告' in action_policy('employee')
    context, _ = await runtime(setup, '给我生成日报', who='admin')
    assert (await execute(context, step=1, action='generate_report', report_date='2026-09-20'))['state'] == 'failed'
