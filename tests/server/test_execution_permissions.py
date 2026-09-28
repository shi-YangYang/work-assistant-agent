"""Execution confirmation never substitutes for business identity/ownership."""
import json
from itertools import product
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from app.agent.operations import execute
from app.agent.interactions import finish_waiting
from app.modules.operations.execution_policy import decide, effective
from app.modules.work.models import WorkItem
from app.modules.operations.models import BusinessAction
from app.tasks.models import Job
from app.tasks.context import RunContext
from app.tasks.queue import claim
from test_business_actions import Judge, create, read_work
from test_company import keyed

pytestmark = pytest.mark.asyncio


async def mode_runtime(setup, mode, text='创建工作：整理需求', who='employee'):
    settings, sessions, users, clients = setup
    response = await clients[who].post('/api/v1/messages', json={'newConversation': True, 'text': text, 'executionMode': mode, 'fullAccessConfirmed': mode == 'full'}, headers=keyed())
    assert response.status_code == 202, response.text
    sent = response.json()
    job = await claim(sessions, users[who].id)
    return RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, intent_model=Judge()), sent


@pytest.mark.parametrize('mode,action', list(product(('ask', 'auto', 'full'), ('create_work', 'update_work', 'delete_work', 'generate_report', 'edit_report', 'submit_report', 'delete_report'))))
async def test_policy_matrix(mode, action):
    expected = 'ask' if mode == 'ask' or mode == 'auto' and action in ('delete_work', 'submit_report', 'delete_report') else 'allow'
    assert decide(mode, action).outcome == expected
    assert decide(mode, action, authorized=False).outcome == 'deny'
    assert decide(mode, action, explicitly_confirm=True).outcome == 'ask'
    assert effective('auto', 'full') == 'auto'
    assert effective('full', 'ask') == 'ask'


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_create_mode_and_exact_approval_continuation(setup, mode):
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, mode)
    result = await execute(context, step=1, action='create_work', changes={'title': '整理需求'})
    assert result['state'] == ('pending' if mode == 'ask' else 'succeeded')
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == (0 if mode == 'ask' else 1)
    if mode != 'ask':
        return
    assert result['preview']['changes']['title'] == '整理需求'
    assert result['confirmLabel'] == '确认创建工作'
    assert await finish_waiting(context)
    confirmed = await clients['employee'].post(f"/api/v1/business-actions/{result['id']}/confirm", json={'expectedRevision': result['revision']})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['state'] == 'succeeded'
    assert confirmed.json()['continuation']['conversationId'] == sent['conversationId']
    repeated = await clients['employee'].post(f"/api/v1/business-actions/{result['id']}/confirm", json={'expectedRevision': result['revision']})
    assert repeated.json() == confirmed.json()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 1
        jobs = (await db.scalars(select(Job).where(Job.owner_id == users['employee'].id))).all()
        assert len(jobs) == 2 and sum(job.state == 'queued' for job in jobs) == 1


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_delete_mode_and_real_owner_protection(setup, mode):
    _, sessions, users, clients = setup
    work = await create(clients['employee'], '待删除')
    context, _ = await mode_runtime(setup, mode, '删除待删除工作')
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='delete_work', target_id=work['id'], expected_revision=1)
    assert result['state'] == ('succeeded' if mode == 'full' else 'pending')
    async with sessions() as db:
        assert (await db.get(WorkItem, work['id'])).deleted == (mode == 'full')
    if mode == 'full':
        peer = await create(clients['peer'], '同事私有事项')
        with pytest.raises(Exception):
            await execute(context, step=2, action='delete_work', target_id=peer['id'], expected_revision=1)
        async with sessions() as db:
            assert not (await db.get(WorkItem, peer['id'])).deleted


async def test_mode_switch_blocked_while_running_and_no_retry_escalation(setup):
    _, sessions, _, clients = setup
    context, sent = await mode_runtime(setup, 'auto')
    conversation = (await clients['employee'].get('/api/v1/conversations/' + sent['conversationId'])).json()
    response = await clients['employee'].patch('/api/v1/conversations/' + sent['conversationId'], json={'expectedRevision': conversation['revision'], 'executionMode': 'full', 'fullAccessConfirmed': True})
    assert response.status_code == 409
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state, job.lease_until = 'awaiting_retry', None
    changed = await clients['employee'].patch('/api/v1/conversations/' + sent['conversationId'], json={'expectedRevision': conversation['revision'], 'executionMode': 'full', 'fullAccessConfirmed': True})
    assert changed.status_code == 200
    from app.modules.operations.execution_policy import mode_for
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert await mode_for(db, job, sent['conversationId']) == 'auto'
        job.result = {}  # legacy job must never gain a later full setting
        assert await mode_for(db, job, sent['conversationId']) == 'auto'


async def test_explicit_review_required_in_full_mode(setup):
    _, _, _, clients = setup
    work = await create(clients['employee'], '先审阅')
    context, _ = await mode_runtime(setup, 'full', '删除前让我看一下')
    class ReviewJudge(Judge):
        async def ainvoke(self, messages):
            answer = await super().ainvoke(messages)
            return AIMessage(content=json.dumps({**json.loads(answer.content), 'requireConfirmation': True}))
    context.intent_model = ReviewJudge()
    await read_work(context, work['id'])
    assert (await execute(context, step=1, action='delete_work', target_id=work['id'], expected_revision=1))['state'] == 'pending'


async def test_ask_update_preview_stale_version_and_rejection(setup):
    _, sessions, _, clients = setup
    work = await create(clients['employee'], '核对字段', summary='原说明', blocker='保留阻碍')
    context, _ = await mode_runtime(setup, 'ask', '将核对字段状态改成已完成')
    await read_work(context, work['id'])
    action = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'status': 'done'})
    assert action['preview']['before'] == {'status': 'in_progress'}
    assert action['preview']['changes'] == {'status': 'done'}
    await finish_waiting(context)
    # Concurrent manual changes invalidate the exact preview instead of applying stale data.
    update = await clients['employee'].post('/api/v1/work-items/' + work['id'] + '/progress', json={'title': work['title'], 'summary': '新说明', 'expectedRevision': 1})
    assert update.status_code == 200
    result = await clients['employee'].post('/api/v1/business-actions/' + action['id'] + '/confirm', json={'expectedRevision': action['revision']})
    assert result.status_code == 409
    cancelled = await clients['employee'].post('/api/v1/business-actions/' + action['id'] + '/cancel', json={'expectedRevision': action['revision']})
    assert cancelled.status_code == 200 and cancelled.json()['state'] == 'cancelled'
    assert cancelled.json()['continuation']
    async with sessions() as db:
        saved = await db.get(WorkItem, work['id'])
        assert saved.content['status'] == 'in_progress' and saved.content['summary'] == '新说明'


@pytest.mark.parametrize('mode,explicit,expected', [('ask', False, 'pending'), ('auto', False, 'pending'), ('full', False, 'succeeded'), ('full', True, 'pending')])
async def test_report_generation_handoff_follows_confirmation_policy(setup, mode, explicit, expected):
    from app.modules.reports.models import Report
    from app.modules.operations.receipts import action_dto
    from app.db.base import now
    _, sessions, users, clients = setup
    await create(clients['employee'], '已确认来源', status='done', summary='已完成来源整理')
    context, sent = await mode_runtime(setup, mode, '生成并提交今天日报')
    class ReviewJudge(Judge):
        async def ainvoke(self, messages):
            result = await super().ainvoke(messages)
            return AIMessage(content=json.dumps({**json.loads(result.content), 'requireConfirmation': explicit}))
    context.intent_model = ReviewJudge()
    result = await execute(context, step=1, action='generate_report', report_date=now().astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date().isoformat(), submit_after=True)
    assert result['state'] == ('pending' if mode == 'ask' or explicit else 'running')
    if result['state'] == 'pending':
        assert '不包含提交' in result['preview']['changes']['范围']
        await finish_waiting(context)
        response = await clients['employee'].post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['state'] == 'running'
    async with sessions.begin() as db:
        row = await db.get(BusinessAction, result['id'])
        report = await db.get(Report, row.result['objectId'])
        report.content = {'completed': '', 'ongoing': '', 'blockers': '', 'next': '整理计划'}
        report.revision += 1
        child = await db.get(Job, row.result['jobId'])
        child.state, child.phase = 'succeeded', 'complete'
        from app.modules.operations.report_completion import complete_report
        await complete_report(db, users['employee'], child)
        assert bool(report.published_revision) == (expected == 'succeeded'), 'Submission must not depend on any GET/DTO projection'
        value = await action_dto(db, users['employee'], row)
        assert value['state'] == expected, value
        assert value['confirmLabel'] == '确认提交报告'
        assert value['action'] == 'submit_report'
        assert bool(report.published_revision) == (expected == 'succeeded')


async def test_approval_batch_replay_never_creates_another_continuation(setup):
    _, sessions, users, clients = setup
    context, _ = await mode_runtime(setup, 'ask', '创建工作A和工作B')
    first = await execute(context, step=1, action='create_work', changes={'title': 'A'})
    second = await execute(context, step=2, action='create_work', changes={'title': 'B'})
    await finish_waiting(context)
    a = await clients['employee'].post('/api/v1/business-actions/' + first['id'] + '/confirm', json={'expectedRevision': first['revision']})
    assert a.status_code == 200 and not a.json().get('continuation')
    b = await clients['employee'].post('/api/v1/business-actions/' + second['id'] + '/confirm', json={'expectedRevision': second['revision']})
    assert b.status_code == 200 and b.json()['continuation']
    async with sessions.begin() as db:
        job = await db.get(Job, b.json()['continuation']['jobId'])
        job.state, job.lease_until = 'succeeded', None
    replay = await clients['employee'].post('/api/v1/business-actions/' + first['id'] + '/confirm', json={'expectedRevision': first['revision']})
    assert replay.status_code == 200, replay.text
    assert replay.json()['continuation'] == b.json()['continuation']
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == users['employee'].id)) == 2


async def test_full_admin_deletion_keeps_its_lease_but_fences_other_readers(setup):
    from app.modules.reports.models import Report, ReportRevision
    from app.modules.messages.models import Message
    from app.agent.tools.actions import query_reports
    from app.security.access import receipt, remember
    from app.tasks.lease import lease
    from test_business_assistant import facts
    from types import SimpleNamespace
    _, sessions, users, clients = setup
    work, rev, source = await facts(sessions, users['employee'])
    async with sessions.begin() as db:
        report = Report(company_id=work.company_id, owner_id=work.owner_id, kind='daily', period='2026-09-16', period_end='2026-09-16', timezone='Asia/Shanghai', content={'completed': '完成整理'}, source_ids=[rev.id], published_revision=1)
        db.add(report); await db.flush()
        public = ReportRevision(company_id=work.company_id, owner_id=work.owner_id, report_id=report.id, revision=1, content=report.content, source_ids=[rev.id])
        db.add(public); await db.flush()
        evidence = receipt('report', public)
    context, _ = await mode_runtime(setup, 'full', '删除员工这份日报及原始材料', 'admin')
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        remember(job, users['admin'], evidence)
        observer = Job(company_id=users['admin'].company_id, owner_id=users['admin'].id, kind='message', target_id=job.target_id, state='awaiting_retry', access=job.access)
        db.add(observer); await db.flush()
        observer_id = observer.id
    await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id)
    result = await execute(context, step=1, action='delete_report', target_id=report.id, expected_revision=1)
    assert result['state'] == 'succeeded', result
    async with sessions.begin() as db:
        job, actor = await lease(db, context)
        assert job.state == 'running'
        assert (await db.get(Job, observer_id)).state == 'cancelled'
        assert (await db.get(Report, report.id)).deleted
        assert (await db.get(Message, source.id)).deleted


async def test_interrupt_closes_pending_approval_and_cannot_revive_task(setup):
    from app.tasks.cancellation import cancel_job, CancelJob
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'ask', '创建工作：待确认')
    action = await execute(context, step=1, action='create_work', changes={'title': '待确认'})
    assert action['state'] == 'pending'
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        await cancel_job(db, users['employee'], job.id, CancelJob(expectedAttempt=job.attempt, expectedFence=job.fence))
    result = await clients['employee'].post('/api/v1/business-actions/' + action['id'] + '/confirm', json={'expectedRevision': action['revision']})
    assert result.status_code == 200 and result.json()['state'] == 'cancelled'
    assert not result.json().get('continuation')
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 0
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == users['employee'].id)) == 1


async def test_old_approval_cannot_write_while_new_input_is_queued(setup):
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'ask', '创建工作A和B')
    first = await execute(context, step=1, action='create_work', changes={'title': 'A'})
    await execute(context, step=2, action='create_work', changes={'title': 'B'})
    await finish_waiting(context)
    message = await clients['employee'].post('/api/v1/messages', json={'conversationId': sent['conversationId'], 'text': '先不要创建，我要修改计划'}, headers=keyed())
    assert message.status_code == 202, message.text
    result = await clients['employee'].post('/api/v1/business-actions/' + first['id'] + '/confirm', json={'expectedRevision': first['revision']})
    assert result.status_code == 409, result.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 0


async def test_each_approval_only_settles_its_own_node_then_finishes_source_stage(setup):
    _, sessions, _, clients = setup
    context, sent = await mode_runtime(setup, 'ask', '创建工作A和B')
    a = await execute(context, step=1, action='create_work', changes={'title': 'A'})
    b = await execute(context, step=2, action='create_work', changes={'title': 'B'})
    await finish_waiting(context)
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        nodes = [{'id': row['id'], 'scope': 's', 'kind': 'tool', 'label': '创建工作', 'state': 'awaiting_confirmation', 'attempts': 1, 'receiptId': row['id'], 'requestKey': row['id']} for row in (a, b)]
        nodes.insert(0, {'id': 'clarification', 'scope': 's', 'kind': 'tool', 'label': '创建工作', 'state': 'awaiting_input', 'attempts': 1, 'requestKey': a['id']})
        job.result = {**job.result, 'nodeExecution': {'scope': 's', 'nodes': nodes}}
    first = await clients['employee'].post('/api/v1/business-actions/' + a['id'] + '/confirm', json={'expectedRevision': a['revision']})
    assert first.status_code == 200, first.text
    before = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['job']
    assert [row['state'] for row in before['nodes']] == ['failed', 'succeeded', 'awaiting_confirmation']
    assert before['state'] == 'awaiting_input'
    second = await clients['employee'].post('/api/v1/business-actions/' + b['id'] + '/cancel', json={'expectedRevision': b['revision']})
    assert second.status_code == 200, second.text
    after = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['job']
    assert [row['state'] for row in after['nodes']] == ['failed', 'succeeded', 'cancelled']
    assert after['state'] == 'succeeded' and after['phase'] == 'complete'
    # Cancellation is retained as an actual unresolved business result, not success.
    assert after['taskOutcome']['state'] == 'partial'
    feedback = (await clients['employee'].get('/api/v1/jobs/' + sent['jobId'] + '/feedback')).json()
    assert feedback['nodes'] == after['nodes']
