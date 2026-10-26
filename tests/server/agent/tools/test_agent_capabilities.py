"""Request intent must survive the message-to-report job boundary."""
import json
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agent.actions.operations import execute
from app.agent.tools.registry import BUSINESS_TOOLS
from app.db.base import now
from app.modules.reports.service import ensure_report
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import create, finish, runtime
from _support.work.report_reliability import CONTENT, ReportModel, prepared
from types import SimpleNamespace
from app.agent.completion.recovery.query_fallback import work_query_fallback
from app.agent.tools.business.work import find_work_items
from app.agent.tools.business.actions import query_reports
from app.modules.work.models import WorkItem

pytestmark = pytest.mark.asyncio


async def test_chat_report_keeps_original_brief_for_single_generation(setup):
    settings, sessions, users, clients = setup
    await create(clients['employee'], '报价方案', summary='已完成初稿', status='in_progress')
    request = '生成本周周报，简洁一点，下一步帮我拟一条可执行建议，标为计划，不要提交。'
    context, _ = await runtime(setup, request)
    result = await execute(context, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    assert result['state'] == 'running'
    await finish(context)
    report_job = await claim(sessions, users['employee'].id)
    assert report_job.result['instructions'] == request
    model = ReportModel()
    await process_job(report_job, sessions, settings, None, model=model)
    assert model.calls == 1 and not model.reviews
    payload = json.loads(model.inputs[0][-1].content)
    assert payload['userRequest'] == request
    assert payload['confirmed'][0]['facts'][0]['summary'] == '已完成初稿'
    async with sessions() as db:
        saved = await db.get(Job, report_job.id)
        assert saved.state == 'succeeded' and saved.result['instructions'] == request


async def test_running_report_does_not_silently_discard_a_different_brief(setup):
    _, sessions, users, clients = setup
    await create(clients['employee'], '周报来源', summary='完成核对')
    async with sessions.begin() as db:
        _, first = await ensure_report(db, users['employee'], 'weekly', now().astimezone(ZoneInfo('Asia/Shanghai')).date(), instructions='请写得简洁')
    async with sessions.begin() as db:
        _, same = await ensure_report(db, users['employee'], 'weekly', now().astimezone(ZoneInfo('Asia/Shanghai')).date(), instructions='请写得简洁')
        assert same.id == first.id
    async with sessions.begin() as db:
        with pytest.raises(HTTPException) as conflict:
            await ensure_report(db, users['employee'], 'weekly', now().astimezone(ZoneInfo('Asia/Shanghai')).date(), instructions='重点写下一步')
        assert conflict.value.status_code == 409
    async with sessions() as db:
        jobs = list((await db.scalars(select(Job).where(Job.owner_id == users['employee'].id))).all())
        assert len(jobs) == 1 and jobs[0].result['instructions'] == '请写得简洁'


async def test_chat_cannot_race_its_own_queued_report_with_an_empty_draft_edit(setup):
    _, sessions, _, clients = setup
    await create(clients['employee'], '报价方案', summary='已完成核对', status='done')
    context, _ = await runtime(setup, '生成本周周报，帮我拟一条下一步计划')
    generation = await execute(context, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    reports = json.loads(await query_reports.coroutine(SimpleNamespace(context=context), report_id=generation['objectId']))
    result = await execute(context, step=2, action='edit_report', target_id=generation['objectId'], expected_revision=reports['items'][0]['revision'], changes={'next': '待核对清单'})
    assert result['id'] == generation['id'] and result['state'] == 'running'
    from app.modules.reports.models import Report
    from app.modules.operations.models import BusinessAction
    async with sessions() as db:
        report = await db.get(Report, generation['objectId'])
        assert not report.edited and not any(report.content.values())
        rows = list((await db.scalars(select(BusinessAction).where(BusinessAction.message_id == generation['messageId']))).all())
        assert len(rows) == 1


async def test_chat_only_exposes_the_usable_report_entrypoint():
    names = {tool.name for tool in BUSINESS_TOOLS}
    assert 'execute_business_action' in names
    assert 'draft_report' not in names


async def test_dropped_query_uses_actual_rows_not_rejected_prose(setup):
    _, sessions, users, clients = setup
    work = await create(clients['employee'], '客户回访', status='blocked', blocker='等待验收')
    await create(clients['peer'], '同事私密工作')
    context, _ = await runtime(setup, '列出我受阻的工作')
    result = await find_work_items.coroutine('', SimpleNamespace(context=context), status='blocked')
    evidence = [{'id': 2, 'tool': 'find_work_items', 'result': result}]
    context.reply_evidence = evidence
    async with sessions() as db:
        fallback = await work_query_fallback(db, users['employee'], context)
        assert '客户回访' in fallback and '等待验收' in fallback
        assert '编造' not in fallback and '同事私密' not in fallback
        assert await work_query_fallback(db, users['peer'], context) == ''
    async with sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        row.revision += 1
    async with sessions() as db:
        assert await work_query_fallback(db, users['employee'], context) == ''


async def test_multi_step_authorization_preserves_reserved_final_answer_budget(setup):
    from app.tasks.nodes.node_execution import initialize, execute_node
    from app.agent.runtime.model import reserve_call
    from app.tasks.context import BudgetExceeded
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'multi-step-review')
    async def operation():
        await reserve_call(context, 'assistant', 10)
        return 'checked'
    # Planning and authorization share the persisted budget; final delivery has reserved capacity.
    for index, kind in enumerate(['model'] * 5 + ['authorization'] * 3 + ['review']):
        assert await execute_node(context, identity=str(index), kind=kind, label=kind, operation=operation) == 'checked'
    assert context.calls == 9
    async with context.sessions.begin() as db:
        live = await db.get(Job, context.job_id)
        budget = live.result['taskBudget']
        regular_limit = budget['policy']['models'] - budget['policy']['reserve_models']
        live.result = {**live.result, 'taskBudget': {**budget, 'models': regular_limit}}
    with pytest.raises(BudgetExceeded):
        await reserve_call(context, 'assistant', 10)
    await reserve_call(context, 'assistant', 10, final_answer=True)
    assert context.calls == regular_limit + 1


@pytest.mark.parametrize('valid_content', [True, False])
async def test_agent_report_single_generation_validates_four_columns_without_review(setup, valid_content):
    settings, sessions, users, _ = setup
    report, job, _ = await prepared(setup)
    original = {'completed': '保留原草稿', 'ongoing': '', 'blockers': '', 'next': '手写备注'}
    from app.modules.reports.models import Report
    async with sessions.begin() as db:
        live = await db.get(Job, job.id)
        live.result = {**live.result, 'instructions': '生成周报，下一步可拟一项合理建议'}
        (await db.get(Report, report.id)).content = original

    class SingleGenerationModel(ReportModel):
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert payload.get('task') not in ('report_fact_review', 'correct_report')
            assert payload['userRequest'] == '生成周报，下一步可拟一项合理建议'
            assert payload['confirmed'][0]['facts'][0]['summary'] == '初稿完成'
            return await super().ainvoke(messages)

    output = CONTENT if valid_content else {'completed': '缺少另外三栏'}
    model = SingleGenerationModel(json.dumps(output, ensure_ascii=False))
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    assert model.calls == 1 and not model.reviews
    async with sessions() as db:
        saved, live = await db.get(Report, report.id), await db.get(Job, job.id)
        assert not live.result.get('reportCorrectionAttempted') and saved.published_revision == 0
        if valid_content:
            assert saved.content == CONTENT and live.state == 'succeeded'
        else:
            assert saved.content == original and live.state == 'failed'
