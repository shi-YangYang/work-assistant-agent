"""Report plans stay separate from progress and use fixed source snapshots."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent.actions.intent import ReportIntentVerdict
from app.agent.actions.operations import execute
from app.agent.tools.business.actions import query_reports
from app.db.base import now
from app.modules.reports.models import Report
from app.modules.reports.service import ensure_report
from app.modules.reports.generation.sources import report_fact_basis
from app.modules.work.models import WorkRevision
from app.tasks.nodes.node_execution import initialize
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.execution_permissions import mode_runtime
from _support.work.report_reliability import ReportModel
from _support.work.work_records import body, create, key

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('field', ['body', 'status', 'summary', 'nextStep'])
async def test_report_authorization_rejects_work_field_coverage(field):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReportIntentVerdict.model_validate({'allowed': True, 'quote': '精简报告，不要提交', 'reason': '', 'requiredFields': [field]})
    with pytest.raises(ValidationError):
        ReportIntentVerdict.model_validate({'allowed': True, 'quote': '精简报告，不要提交', 'reason': '', 'requestedChanges': [{'quote': '精简报告', 'field': field}]})


async def test_report_generation_and_rewrite_keep_plans_separate_and_snapshot_fixed(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    original_plan = '未来计划：下周完成移动端上线，当前尚未完成。'
    work = await create(client, body=body(original_plan))
    path = '/api/v1/work-items/' + work['id']
    facts = ['已完成客户需求核对，确认在线询价入口。', '已完成首页初稿，并收到客户确认。']
    for index, text in enumerate(facts):
        response = await client.post(path + '/updates', json={'expectedRevision': index + 1, 'text': text}, headers=key())
        assert response.status_code == 201, response.text
    async with sessions.begin() as db:
        report, job = await ensure_report(db, users['employee'], 'weekly', now().date(), report_timezone='UTC', instructions='保留本周两件已完成事实，把尚未完成的计划放到下一步，不提交。')
        source_ids = list(job.result['sourceIds'])
    content = {'completed': '\n'.join(facts), 'ongoing': '', 'blockers': '', 'next': '计划下周完成移动端上线，目前尚未完成。'}
    model = ReportModel(json.dumps(content, ensure_ascii=False))
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    generated_payload = json.loads(model.inputs[0][-1].content)
    reviewed_payload = json.loads(model.reviews[0][-1].content)
    assert [item['content']['summary'] for item in generated_payload['confirmed']] == facts
    assert all('bodyText' not in item['content'] and 'body' not in item['content'] for item in generated_payload['confirmed'])
    contexts = generated_payload['workContextsForPlansOnly']
    assert len(contexts) == 1 and contexts[0]['bodyText'] == original_plan
    assert contexts[0]['sourceId'] in source_ids and contexts[0]['workId'] == work['id']
    assert reviewed_payload['workContextsForPlansOnly'] == contexts
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        assert saved.content == content and saved.source_ids == source_ids and not saved.published_revision
        original_revision = saved.revision
        snapshots = {row.id: row.content for row in (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(source_ids)))).all()}
    changed = await client.patch(path, json={'expectedRevision': 3, 'body': body('新计划：改为明年做桌面端。')}, headers=key())
    assert changed.status_code == 200, changed.text

    request = '把刚才周报的措辞改得简洁一些，仍保留两项已完成事实和未完成计划，不要提交。'
    context, _ = await mode_runtime(setup, 'full', request)
    context.node_retry = True
    await initialize(context, 'report-rewrite-plan-context')
    preview = json.loads(await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id))
    assert preview['items'][0]['sourceFacts']['workContextsForPlansOnly'] == contexts

    class RewriteJudge:
        def __init__(self):
            self.authorizations = 0
            self.reviews = []

        async def ainvoke(self, messages):
            payload = next(json.loads(message.content) for message in messages if message.type == 'human' and message.content.startswith('{'))
            if payload.get('task') == 'report_fact_review':
                self.reviews.append(payload)
                return AIMessage(content='{"valid":true}')
            self.authorizations += 1
            # A malformed judge result is repaired inside authorization; it
            # must never ask the assistant to add work fields to edit_report.
            fields = ['body', 'status'] if self.authorizations == 1 else ['completed', 'next']
            return AIMessage(content=json.dumps({'allowed': True, 'quote': request, 'reason': '', 'requiredFields': fields,
                'requestedChanges': [{'quote': '措辞改得简洁一些', 'field': field, 'kind': 'explicit_field'} for field in fields]}))

    judge = context.intent_model = RewriteJudge()
    changes = {'completed': '需求核对及询价入口已确认；首页初稿获客户确认。', 'next': '计划下周上线移动端，尚未完成。'}
    result = await execute(context, step=1, action='edit_report', target_id=report.id, expected_revision=original_revision, changes=changes)
    assert result['state'] == 'succeeded', result
    assert judge.authorizations == 2
    assert judge.reviews[0]['workContextsForPlansOnly'] == contexts
    assert {item['content']['summary'] for item in judge.reviews[0]['confirmed']} == set(facts)
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        assert saved.revision == original_revision + 1 and saved.content == {**content, **changes}
        assert saved.source_ids == source_ids and not saved.published_revision
        assert (await report_fact_basis(db, users['employee'], saved, full=True))['workContextsForPlansOnly'] == contexts
        assert {row.id: row.content for row in (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(source_ids)))).all()} == snapshots
