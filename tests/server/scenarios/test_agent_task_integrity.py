from zoneinfo import ZoneInfo
"""Regressions for partial tasks, scoped reads and resumable report handoffs."""
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent.actions.operations import execute
from app.agent.completion.recovery.query_fallback import latest_query, work_query_fallback
from app.agent.tools.business.actions import query_reports
from app.agent.tools.business.work import find_work_items
from app.db.base import now
from app.modules.messages.models import Message
from app.modules.reports.models import Report
from app.modules.reports.service import ensure_report
from app.modules.reports.generation.sources import report_fact_basis
from app.modules.work.models import WorkItem
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import Judge, create, finish, run_reply, runtime
from _support.work.report_reliability import CONTENT, ReportModel, prepared
from _support.agent.agent_eval_cases import cases, failures
from _support.agent.agent_eval_grading import grading_input, parse_grade

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('complete', [True, False])
@pytest.mark.parametrize('answer', ['已创建工作。', ''])
async def test_partial_task_preserves_missing_step_and_never_claims_full_success(setup, monkeypatch, complete, answer):
    calls, receipts = [], []
    async def graph(context, saver, content, model, **options):
        calls.append(options)
        context.intent_model = Judge()
        # A replay keeps the first operation's exact receipt and object identity.
        for _ in range(2):
            receipts.append(await execute(context, step=1, action='create_work', changes={'title': '任务A'}))
        if complete:
            await execute(context, step=2, action='create_work', changes={'title': '任务B'})
        from _support.agent.fakes import set_delivery
        task = {'state': 'completed'} if complete else {'state': 'blocked', 'remaining': ['尚未创建任务B']}
        await set_delivery(context, answer, business=True, task=task)
        return answer
    class UnusedJudge:
        async def ainvoke(self, messages):
            raise AssertionError('Explicit remaining state must not invoke a blanket prose judge')
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    data = await run_reply(setup, '分别创建任务A和任务B', '', UnusedJudge())
    assert calls == [{}]
    assert receipts[0]['id'] == receipts[1]['id']
    assert len(data['actions']) == (2 if complete else 1)
    assert data['job']['state'] == ('succeeded' if complete else 'awaiting_input')
    assert data['job']['incompleteTask'] is not complete
    assert data['job']['taskOutcome']['state'] == ('completed' if complete else 'partial')
    assert data['job']['taskOutcome']['remaining'] == ([] if complete else ['尚未创建任务B'])
    feedback = await setup[3]['employee'].get('/api/v1/jobs/' + data['job']['id'] + '/feedback')
    assert feedback.json()['incompleteTask'] is not complete
    assert ('仍有操作未完成' in data['reply']) is not complete


async def test_query_fallback_respects_last_filter_and_empty_result(setup):
    _, sessions, users, clients = setup
    await create(clients['employee'], '受阻工作', status='blocked', blocker='等待资料')
    await create(clients['employee'], '完成工作', status='done')
    context, _ = await runtime(setup, '先看工作，最后只列受阻项')
    for args in ({}, {'status': 'blocked'}):
        result = await find_work_items.coroutine('', SimpleNamespace(context=context), **args)
        context.reply_evidence.append({'id': len(context.reply_evidence), 'tool': 'find_work_items', 'result': result})
    async with sessions() as db:
        reply = await work_query_fallback(db, users['employee'], context)
    assert '受阻工作' in reply and '完成工作' not in reply
    result = await find_work_items.coroutine('不存在的关键词', SimpleNamespace(context=context))
    context.reply_evidence.append({'id': 3, 'tool': 'find_work_items', 'result': result})
    async with sessions() as db:
        reply = await work_query_fallback(db, users['employee'], context)
    assert '没有找到' in reply and '受阻工作' not in reply


async def test_query_fallback_joins_only_matching_cursor_chain():
    def page(ids, status, cursor='', next_cursor=None):
        return {'tool': 'find_work_items', 'result': json.dumps({'items': [{'id': i, 'revision': 1} for i in ids], 'filters': {'status': status}, 'cursor': cursor, 'nextCursor': next_cursor})}
    rows, partial, _ = latest_query([page(['wrong'], ''), page(['a'], 'blocked', next_cursor='c1'), page(['b'], 'done', next_cursor='c1'), page(['c'], 'blocked', cursor='c1')])
    assert [r['id'] for r in rows] == ['a', 'c'] and not partial
    rows, partial, _ = latest_query([page(['a'], 'blocked', next_cursor='c1'), page(['c'], 'blocked', cursor='missing')])
    assert [r['id'] for r in rows] == ['c'] and partial


@pytest.mark.parametrize('revoke', [False, True])
async def test_report_receives_referenced_style_and_rechecks_source_access(setup, revoke):
    settings, sessions, users, clients = setup
    await create(clients['employee'], '项目验收', summary='已经完成验收', status='done')
    previous, sent = await runtime(setup, '周报每栏不超过30字，下一步列两个编号步骤。')
    async with sessions.begin() as db:
        (await db.get(Message, sent['messageId'])).reply = '按每栏不超过30字，下一步两个编号步骤整理。'
    await finish(previous)
    context, _ = await runtime(setup, '按刚才的要求生成本周周报，不提交。')
    await execute(context, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    await finish(context)
    if revoke:
        async with sessions.begin() as db:
            (await db.get(Message, sent['messageId'])).deleted = True
    model = ReportModel()
    job = await claim(sessions, users['employee'].id)
    await process_job(job, sessions, settings, None, model=model)
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert bool(live.result.get('reportSaved')) is not revoke
    assert not model.reviews
    assert len(model.inputs) == (0 if revoke else 1)
    if not revoke:
        payload = json.loads(model.inputs[0][-1].content)
        assert '30字' in json.dumps(payload['conversationForReferenceOnly'], ensure_ascii=False)


@pytest.mark.parametrize('fail_at', ['generating', 'saving'])
async def test_report_retry_resumes_current_stage_without_duplicate_save(setup, monkeypatch, fail_at):
    from app.agent import reports
    settings, sessions, users, clients = setup
    report, job, _ = await prepared(setup)
    failed = False
    class InterruptedModel(ReportModel):
        async def ainvoke(self, messages):
            nonlocal failed
            assert 'task' not in json.loads(messages[-1].content)
            answer = await super().ainvoke(messages)
            if fail_at == 'generating' and not failed:
                failed = True
                raise httpx.ReadTimeout('controlled generation interruption')
            return answer
    original_save = reports.save_candidate
    async def interrupted_save(db, context, content):
        nonlocal failed
        if fail_at == 'saving' and not failed:
            failed = True
            raise httpx.ReadTimeout('controlled save interruption')
        return await original_save(db, context, content)
    monkeypatch.setattr(reports, 'save_candidate', interrupted_save)
    model = InterruptedModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    async with sessions() as db:
        interrupted = await db.get(Job, job.id)
        assert interrupted.state == 'failed' and not interrupted.result.get('reportSaved')
        assert interrupted.result['reportDraft']['stage'] == ('generate' if fail_at == 'generating' else 'ready')
        saved = await db.get(Report, report.id)
        assert saved.revision == report.revision and not any(saved.content.values())
    assert (await clients['employee'].post('/api/v1/jobs/' + job.id + '/retry', json={})).status_code == 200
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert live.state == 'succeeded' and 'reportDraft' not in live.result
        saved = await db.get(Report, report.id)
        assert saved.content == CONTENT and saved.revision == report.revision + 1
        assert live.result['savedRevision'] == saved.revision and live.result['reportSaved']
    assert model.calls == (2 if fail_at == 'generating' else 1) and not model.reviews
    assert (await clients['employee'].post('/api/v1/jobs/' + job.id + '/retry', json={})).status_code == 409


async def test_distinct_same_title_creations_preserve_replay_and_legacy_receipts(setup):
    _, sessions, users, _ = setup
    context, _ = await runtime(setup, '建两个客户回访，一个说明甲客户，另一个说明乙客户。')
    first = await execute(context, step=1, action='create_work', changes={'title': '客户回访', 'summary': '甲客户'})
    from app.modules.operations.models import BusinessAction
    from app.core.digests import digest
    async with sessions.begin() as db:
        # Receipts from before the identity change still deduplicate retries.
        row = await db.get(BusinessAction, first['id'])
        row.intent_key = digest({'action': 'create_work', 'title': '客户回访'})
    again = await execute(context, step=3, action='create_work', changes={'title': '客户回访', 'summary': '甲客户'})
    second = await execute(context, step=2, action='create_work', changes={'title': '客户回访', 'summary': '乙客户'})
    assert again['id'] == first['id'] and second['objectId'] != first['objectId']
    async with sessions() as db:
        rows = list((await db.scalars(select(WorkItem).where(WorkItem.owner_id == users['employee'].id))).all())
        assert sorted(row.content['summary'] for row in rows) == ['乙客户', '甲客户']
    assert context.intent_model.inputs[-1]['completedOrPendingSteps'][0]['details']['summary'] == '甲客户'


async def test_edit_report_checks_all_sources_beyond_query_preview_limit(setup):
    _, sessions, users, clients = setup
    for index in range(3):
        await create(clients['employee'], '长工作' + str(index), summary='来源说明。' * 500)
    async with sessions.begin() as db:
        report, job = await ensure_report(db, users['employee'], 'weekly', now().astimezone(ZoneInfo('Asia/Shanghai')).date())
        report.source_ids = job.result['sourceIds']
        report.content = CONTENT
        job.state = 'succeeded'
        assert not (await report_fact_basis(db, users['employee'], report))['complete']
    context, _ = await runtime(setup, '只把周报下一步改成继续核对，其它不动。')
    await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id)
    class FullJudge(Judge):
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert payload.get('task') != 'report_fact_review'
            facts = payload['proposedOperation']['reportSourceFacts']
            assert facts['complete'] and len(facts['items']) == 3
            assert all(item['content']['summary'] == '来源说明。' * 500 for item in facts['items'])
            return await super().ainvoke(messages)
    context.intent_model = FullJudge()
    result = await execute(context, step=1, action='edit_report', target_id=report.id, expected_revision=report.revision, changes={'next': '继续核对'})
    assert result['state'] == 'succeeded'
    assert len(context.intent_model.inputs) == 1
    assert len(context.intent_model.inputs[-1]['proposedOperation']['reportSourceFacts']['items']) == 3


async def test_writing_evaluation_cannot_pass_refusal_without_semantic_completion():
    case = next(c for c in cases() if c.id == 'random_report-01')
    refusal = '这是示例报告请求，但我无法替你生成。请自行梳理工作并手动填写。' * 3
    snapshot = {'works': [], 'reports': [], 'actions': [], 'jobs': [], 'messages': [{'reply': refusal}]}
    assert failures(case, snapshot)
    payload = grading_input(case, snapshot)
    snapshot['semantic'] = parse_grade(json.dumps({'satisfied': False, 'reason': '只有拒绝和填写建议，没有报告正文', 'evidence': [refusal]}), payload)
    assert failures(case, snapshot)
    for raw in ('{"satisfied":"true","reason":"","evidence":[]}', '{"satisfied":true,"reason":"","evidence":["不存在的正文"]}'):
        with pytest.raises(ValueError):
            parse_grade(raw, payload)
