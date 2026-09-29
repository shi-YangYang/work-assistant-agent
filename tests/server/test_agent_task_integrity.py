from zoneinfo import ZoneInfo
"""Regressions for partial tasks, scoped reads and resumable report handoffs."""
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent.operations import execute
from app.agent.query_fallback import latest_query, work_query_fallback
from app.agent.tools.actions import query_reports
from app.agent.tools.work import find_work_items
from app.db.base import now
from app.modules.messages.models import Message
from app.modules.reports.models import Report
from app.modules.reports.service import ensure_report
from app.modules.reports.sources import report_fact_basis
from app.modules.work.models import WorkItem
from app.tasks.handlers import process_job
from app.tasks.models import Job
from app.tasks.queue import claim
from test_business_actions import Judge, create, finish, run_reply, runtime
from test_report_reliability import CONTENT, ReportModel, prepared
from agent_eval_cases import cases, failures
from agent_eval_grading import grading_input, parse_grade

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('complete', [True, False])
@pytest.mark.parametrize('answer', ['已创建工作。', ''])
async def test_partial_task_repairs_only_missing_step_and_never_claims_full_success(setup, monkeypatch, complete, answer):
    calls, receipts = [], []
    async def graph(context, saver, content, model, **options):
        calls.append(options)
        context.intent_model = Judge()
        # Replaying the first call must keep its receipt and object identity.
        receipts.append(await execute(context, step=1, action='create_work', changes={'title': '任务A'}))
        if options.get('repair_missing_action') and complete:
            await execute(context, step=2, action='create_work', changes={'title': '任务B'})
        from fakes import set_delivery
        await set_delivery(context, answer, business=True)
        return answer
    class CompletionJudge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            return AIMessage(content=json.dumps({'issues': ([{'kind': 'execution', 'quote': payload['answer'], 'reason': '使用实际回执'}] if payload['answer'] else []) + ([{'kind': 'missing_action', 'reason': '尚未创建任务B'}] if len(payload['currentActions']) < 2 else [])}))
    monkeypatch.setattr('app.tasks.handlers.invoke_harness', graph)
    data = await run_reply(setup, '分别创建任务A和任务B', '', CompletionJudge())
    assert len(calls) == 2 and calls[1] == {'repair_missing_action': True}
    assert receipts[0]['id'] == receipts[1]['id']
    assert len(data['actions']) == (2 if complete else 1)
    assert data['job']['state'] == ('succeeded' if complete else 'awaiting_input')
    assert data['job']['incompleteTask'] is not complete
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
    previous, sent = await runtime(setup, '日报每栏不超过30字，下一步列两个编号步骤。')
    async with sessions.begin() as db:
        (await db.get(Message, sent['messageId'])).reply = '按每栏不超过30字，下一步两个编号步骤整理。'
    await finish(previous)
    context, _ = await runtime(setup, '按刚才的要求生成今天日报，不提交。')
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
    if revoke:
        assert not model.inputs
    else:
        for request in (model.inputs[0], model.reviews[0]):
            payload = json.loads(request[-1].content)
            assert '30字' in json.dumps(payload['conversationForReferenceOnly'], ensure_ascii=False)


@pytest.mark.parametrize('fail_at', ['correcting', 'corrected_review'])
async def test_report_retry_resumes_correction_without_regenerating_initial_draft(setup, fail_at):
    settings, sessions, users, clients = setup
    report, job, _ = await prepared(setup)
    async with sessions.begin() as db:
        live = await db.get(Job, job.id)
        live.result = {**live.result, 'instructions': '生成日报并拟定下一步'}
    tasks = []
    failed = False
    class InterruptedModel:
        async def ainvoke(self, messages):
            nonlocal failed
            payload = json.loads(messages[-1].content)
            task = payload.get('task', 'generate')
            tasks.append(task)
            correcting = task == 'correct_report'
            corrected_review = task == 'report_fact_review' and payload['report'] == CONTENT
            if not failed and ((fail_at == 'correcting' and correcting) or (fail_at == 'corrected_review' and corrected_review)):
                failed = True
                raise httpx.ReadTimeout('controlled interruption')
            if task == 'report_fact_review':
                return AIMessage(content=json.dumps({'valid': corrected_review, 'reason': '' if corrected_review else '初稿完成不能扩成全部完成'}))
            return AIMessage(content=json.dumps(CONTENT if correcting else {**CONTENT, 'completed': '全部完成'}))
    model = InterruptedModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    assert (await clients['employee'].post('/api/v1/jobs/' + job.id + '/retry', json={})).status_code == 200
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert live.state == 'succeeded' and 'reportDraft' not in live.result
        assert (await db.get(Report, report.id)).content == CONTENT
    assert tasks.count('generate') == 1
    assert tasks.count('correct_report') == (2 if fail_at == 'correcting' else 1)


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
        report, job = await ensure_report(db, users['employee'], 'daily', now().astimezone(ZoneInfo('Asia/Shanghai')).date())
        report.source_ids = job.result['sourceIds']
        report.content = CONTENT
        job.state = 'succeeded'
        assert not (await report_fact_basis(db, users['employee'], report))['complete']
    context, _ = await runtime(setup, '只把日报下一步改成继续核对，其它不动。')
    await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id)
    reviewed = []
    class FullJudge(Judge):
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            if payload.get('task') == 'report_fact_review':
                reviewed.append(payload)
            return await super().ainvoke(messages)
    context.intent_model = FullJudge()
    result = await execute(context, step=1, action='edit_report', target_id=report.id, expected_revision=report.revision, changes={'next': '继续核对'})
    assert result['state'] == 'succeeded'
    assert len(reviewed[0]['confirmed']) == 3
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
