"""Complete in-period work content, source identity and live write protection."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from app.db.base import now
from app.modules.reports.models import Report
from app.modules.reports.service import ensure_report
from app.modules.reports.generation.sources import report_inputs, source_payload, sources_for
from app.modules.work.models import WorkItem, WorkRevision, WorkUpdate
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.work.report_reliability import ReportModel, CONTENT
from _support.work.work_records import body, create, key

pytestmark = pytest.mark.asyncio


async def test_body_checklist_only_work_generates_with_checked_state_and_distinct_identity(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    checklist = {'schemaVersion': 1, 'content': [{'type': 'taskList', 'content': [
        {'type': 'taskItem', 'attrs': {'checked': checked}, 'content': body(text)['content']}
        for checked, text in [(True, '资料已归档'), (False, '准备会议议程')]]}]}
    first = await create(client, title='周会准备', body=checklist)
    second = await create(client, title='周会准备', body=body('尚未联系客户，需先确认时间'))
    async with sessions.begin() as db:
        assert not list((await db.scalars(select(WorkUpdate).where(WorkUpdate.owner_id == users['employee'].id))).all())
        report, job = await ensure_report(db, users['employee'], 'weekly', now().date(), report_timezone='UTC')
    model = ReportModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    rows = [item['content'] for item in json.loads(model.inputs[0][-1].content)['confirmed']]
    assert {row['workId'] for row in rows} == {first['id'], second['id']}
    selected = next(row for row in rows if row['workId'] == first['id'])
    assert [item['attrs']['checked'] for item in selected['body']['content'][0]['content']] == [True, False]
    assert selected['status'] == 'in_progress' and selected['revision'] == 1 and selected['recordedAt']
    assert model.calls == 1 and not model.reviews
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        assert saved.content == CONTENT and not saved.published_revision
        assert (await db.get(Job, job.id)).result['reportSaved']


async def test_states_reopening_progress_and_post_period_body_do_not_overwrite_history(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client, body=body('周期内正文'))
    path = '/api/v1/work-items/' + work['id']
    for revision, status in [(1, 'done'), (2, 'in_progress')]:
        assert (await client.patch(path, json={'expectedRevision': revision, 'status': status}, headers=key())).status_code == 200
    assert (await client.patch(path, json={'expectedRevision': 3, 'body': body('周期之后机密新计划')}, headers=key())).status_code == 200
    start = datetime(2026, 10, 18, 16, tzinfo=timezone.utc)
    async with sessions.begin() as db:
        rows = list((await db.scalars(select(WorkRevision).where(WorkRevision.work_id == work['id']).order_by(WorkRevision.revision))).all())
        for index, row in enumerate(rows):
            row.created_at = start + timedelta(days=0 if index < 3 else 7)
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id,
                        kind='weekly', period='2026-10-19', period_end='2026-10-25', timezone='Asia/Shanghai')
        await db.flush()
        selected = await report_inputs(db, report)
        payload = await source_payload(db, selected)
        assert [row['content']['status'] for row in payload] == ['in_progress', 'done', 'in_progress']
        assert len([row for row in payload if row['content'].get('body')]) == 1
        assert payload[-1]['content']['bodyText'] == '周期内正文'
        assert '周期之后' not in json.dumps(payload, ensure_ascii=False)
        with pytest.raises(ValueError):
            await sources_for(db, report, users['peer'], [row.id for row in selected])
        (await db.get(WorkItem, work['id'])).deleted = True
        await db.flush()
        with pytest.raises(ValueError):
            await sources_for(db, report, users['employee'], [row.id for row in selected])


async def test_deleted_corrected_progress_is_not_revived_and_other_progress_survives(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    first = (await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '错误成果'}, headers=key())).json()
    second = (await client.post(path + '/updates', json={'expectedRevision': 2, 'text': '保留的真实成果'}, headers=key())).json()
    edited = await client.patch(path + '/updates/' + first['update']['id'], json={
        'expectedRevision': 3, 'expectedUpdateRevision': 1, 'text': '纠正后的成果'}, headers=key())
    assert edited.status_code == 200, edited.text
    async with sessions.begin() as db:
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id,
                        kind='weekly', period=now().date().isoformat(), period_end=now().date().isoformat(), timezone='UTC')
        payload = await source_payload(db, await report_inputs(db, report))
        summaries = [row['content']['summary'] for row in payload if row['content']['summary']]
        assert set(summaries) == {'纠正后的成果', '保留的真实成果'}
        (await db.get(WorkUpdate, first['update']['id'])).deleted = True
        await db.flush()
        payload = await source_payload(db, await report_inputs(db, report))
        assert [row['content']['summary'] for row in payload if row['content']['summary']] == ['保留的真实成果']
        assert '错误成果' not in json.dumps(payload, ensure_ascii=False)


async def test_source_change_during_generation_blocks_commit(setup):
    settings, sessions, users, clients = setup
    work = await create(clients['employee'])
    path = '/api/v1/work-items/' + work['id']
    response = (await clients['employee'].post(path + '/updates', json={'expectedRevision': 1, 'text': '将被撤销的进展'}, headers=key())).json()
    async with sessions.begin() as db:
        report, job = await ensure_report(db, users['employee'], 'weekly', now().date(), report_timezone='UTC')
    async def changed():
        async with sessions.begin() as db:
            (await db.get(WorkUpdate, response['update']['id'])).deleted = True
    model = ReportModel(callback=changed)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert live.state == 'failed' and not live.result.get('reportSaved')
        assert not any((await db.get(Report, report.id)).content.values())
    assert model.calls == 1 and not model.reviews


async def test_authorized_report_clear_is_allowed_but_empty_generation_is_not(setup):
    from app.agent.actions.operations import execute
    from app.agent.tools.business.actions import query_reports
    from types import SimpleNamespace
    from _support.agent.execution_permissions import mode_runtime
    from _support.work.report_reliability import prepared
    from app.modules.reports.generation.validation import validate_content
    settings, sessions, users, clients = setup
    report, job, _ = await prepared(setup)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    context, _ = await mode_runtime(setup, 'full', '清空这份周报的四个栏目，不要提交')
    await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id)
    saved = (await clients['employee'].get('/api/v1/reports/' + report.id)).json()
    empty = dict.fromkeys(CONTENT, '')
    result = await execute(context, step=1, action='edit_report', target_id=report.id,
                           expected_revision=saved['revision'], changes=empty)
    assert result['state'] == 'succeeded', result
    assert (await clients['employee'].get('/api/v1/reports/' + report.id)).json()['content'] == empty
    with pytest.raises(ValueError):
        validate_content(empty)


async def test_rewrite_rechecks_source_access_after_authorization(setup):
    from types import SimpleNamespace
    from app.agent.actions.operations import execute
    from app.agent.tools.business.actions import query_reports
    from _support.agent.execution_permissions import mode_runtime
    from _support.agent.business_actions import Judge
    from _support.work.report_reliability import prepared
    settings, sessions, users, clients = setup
    report, job, work = await prepared(setup)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    context, _ = await mode_runtime(setup, 'full', '精简周报正文，不要提交')
    await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id)
    class ChangingJudge(Judge):
        async def ainvoke(self, messages):
            answer = await super().ainvoke(messages)
            async with sessions.begin() as db:
                (await db.get(WorkItem, work.id)).deleted = True
            return answer
    context.intent_model = ChangingJudge()
    saved = (await clients['employee'].get('/api/v1/reports/' + report.id)).json()
    result = await execute(context, step=1, action='edit_report', target_id=report.id,
                           expected_revision=saved['revision'], changes={'ongoing': '待确认'})
    assert result['state'] == 'conflict' and '来源已变化' in result['message']
    assert (await clients['employee'].get('/api/v1/reports/' + report.id)).json()['content'] == CONTENT
