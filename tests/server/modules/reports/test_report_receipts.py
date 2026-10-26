"""Saved report fields and child retry state come from actual business rows."""
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json

import pytest
from langchain_core.messages import AIMessage

from app.agent.actions.operations import execute
from app.db.base import now
from app.modules.operations.models import BusinessAction
from app.modules.operations.report_receipts import snapshot
from app.modules.reports.models import Report
from app.modules.reports.generation.parsing import parse_report
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import Judge, create, finish
from _support.agent.execution_permissions import mode_runtime
from _support.work.report_reliability import CONTENT, ReportModel


def test_report_snapshot_distinguishes_empty_truncated_and_candidate_fields():
    report = SimpleNamespace(revision=4, published_revision=2, content=CONTENT,
                             candidate={'content': {**CONTENT, 'blockers': '受控阻碍' * 100}})
    saved = snapshot(report)
    candidate = snapshot(report, candidate=True)
    assert saved['content'] == CONTENT and saved['emptyFields'] == ['blockers']
    assert saved['truncatedFields'] == [] and saved['status'] == 'saved'
    assert candidate['status'] == 'candidate' and candidate['revision'] == 4
    assert candidate['emptyFields'] == [] and candidate['truncatedFields'] == ['blockers']
    assert candidate['fieldChars']['blockers'] == 400 and len(candidate['content']['blockers']) == 240


@pytest.mark.parametrize('content,reason', [
    ('private-invalid-body', 'report_json'),
    (json.dumps({'secret': 'private-invalid-body'}), 'report_fields'),
    (json.dumps({**CONTENT, 'blockers': ['private-invalid-body']}), 'report_schema'),
    (json.dumps(dict.fromkeys(CONTENT, '')), 'report_empty'),
])
def test_report_parse_failure_records_shape_without_body(content, reason):
    events = []
    with pytest.raises(ValueError):
        parse_report(AIMessage(content=content, response_metadata={'finish_reason': 'stop'}),
                     on_timing=lambda event, **fields: events.append((event, fields)))
    assert len(events) == 1 and events[0][0] == 'report.invalid_response'
    assert events[0][1] == {'reason': reason, 'finish_reason': 'stop', 'body_chars': len(content), 'tool_count': 0}
    assert 'private-invalid-body' not in json.dumps(events)


async def requested_report(setup, *, submit=False):
    await create(setup[3]['employee'], title='方案', summary='方案初稿已完成', status='done')
    context, sent = await mode_runtime(setup, 'full', '根据已有工作生成并提交本周周报' if submit else '生成本周周报草稿')
    accepted = await execute(context, step=1, action='generate_report', report_kind='weekly',
                             report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), submit_after=submit)
    assert accepted['state'] == 'running'
    await finish(context)
    return context, sent, accepted


@pytest.mark.asyncio
async def test_submitted_receipt_freezes_actual_fields_and_not_later_edits(setup):
    settings, sessions, users, clients = setup
    context, sent, accepted = await requested_report(setup, submit=True)
    model = ReportModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    url = '/api/v1/messages/' + sent['messageId']
    message = (await clients['employee'].get(url)).json()
    card = message['actions'][0]
    assert card['action'] == 'submit_report' and card['state'] == 'succeeded'
    evidence = card['reportSnapshot']
    assert evidence['content'] == CONTENT and evidence['emptyFields'] == ['blockers']
    assert evidence['revision'] == evidence['publishedRevision'] == card['objectRevision']
    async with sessions.begin() as db:
        report = await db.get(Report, accepted['objectId'])
        report.content = {**CONTENT, 'blockers': '之后用户手填的风险'}
        report.revision += 1
    later = (await clients['employee'].get(url)).json()['actions'][0]
    assert later['reportSnapshot'] == evidence
    assert model.calls == 1 and len(model.reviews) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed', [True, False])
async def test_submit_authorization_receives_bounded_current_saved_version_without_bypassing_permission(setup, allowed):
    from app.agent.tools.business.actions import query_reports
    settings, sessions, users, _ = setup
    _, _, accepted = await requested_report(setup)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    async with sessions.begin() as db:
        report = await db.get(Report, accepted['objectId'])
        report.content = {**CONTENT, 'ongoing': '已保存的进行中内容' * 80}
        report.candidate = {'content': {**CONTENT, 'blockers': '未采纳的候选风险'}}
        expected = {'id': report.id, 'kind': report.kind, 'period': report.period,
                    'candidateAvailable': True, **snapshot(report)}
    context, _ = await mode_runtime(setup, 'full', '现在确认提交刚才这份周报。')
    context.intent_model = Judge(allowed=allowed)
    await query_reports.coroutine(SimpleNamespace(context=context), report_id=accepted['objectId'])
    result = await execute(context, step=1, action='submit_report', target_id=accepted['objectId'],
                           expected_revision=expected['revision'])
    assert len(context.intent_model.inputs) == 1
    payload = context.intent_model.inputs[0]
    assert payload['currentUserText'] == '现在确认提交刚才这份周报。'
    proposal = payload['proposedOperation']
    assert proposal['targetReport'] == expected
    assert expected['status'] == 'saved' and expected['emptyFields'] == ['blockers']
    assert expected['truncatedFields'] == ['ongoing'] and expected['publishedRevision'] == 0
    assert '未采纳的候选风险' not in json.dumps(expected, ensure_ascii=False)
    assert result['state'] == ('succeeded' if allowed else 'failed')
    async with sessions() as db:
        report = await db.get(Report, accepted['objectId'])
        assert report.published_revision == (expected['revision'] if allowed else 0)


@pytest.mark.asyncio
async def test_failed_report_child_is_projected_as_failed_and_same_retry_recovers(setup):
    settings, sessions, users, clients = setup
    context, sent, accepted = await requested_report(setup)
    child = await claim(sessions, users['employee'].id)
    async with sessions.begin() as db:
        current = await db.get(Job, child.id)
        current.request_started = True
    invalid = ReportModel(content='invalid-json')
    await process_job(child, sessions, settings, None, model=invalid)
    url = '/api/v1/messages/' + sent['messageId']
    message = (await clients['employee'].get(url)).json()
    card = message['actions'][0]
    assert card['state'] == 'failed' and card['job']['state'] == 'awaiting_retry'
    assert card['message'] == '报告尚未生成，请打开报告查看原因或重试。'
    assert card['job']['id'] == child.id and card['objectId'] == accepted['objectId']
    assert message['job']['taskOutcome']['state'] == 'blocked'
    assert '未完成' in message['job']['taskOutcome']['reason']
    assert invalid.calls == 1 and not invalid.reviews
    async with sessions.begin() as db:
        stored = await db.get(BusinessAction, accepted['id'])
        assert stored.state == 'running'
        # Persisted failure projections must not leak into the next attempt.
        stored.result = {**stored.result, 'message': card['message']}
    retried = await clients['employee'].post('/api/v1/jobs/' + child.id + '/retry', json={})
    assert retried.status_code == 200, retried.text
    waiting = (await clients['employee'].get(url)).json()['actions'][0]
    assert waiting['state'] == 'running' and waiting['job']['state'] == 'queued'
    assert waiting['message'] == ''
    resumed = await claim(sessions, users['employee'].id)
    running = (await clients['employee'].get(url)).json()['actions'][0]
    assert running['state'] == 'running' and running['job']['state'] == 'running'
    assert running['message'] == ''
    model = ReportModel()
    await process_job(resumed, sessions, settings, None, model=model)
    final = (await clients['employee'].get(url)).json()
    assert final['actions'][0]['id'] == accepted['id']
    assert final['actions'][0]['state'] == 'succeeded'
    assert final['actions'][0]['message'] == ''
    assert final['actions'][0]['reportSnapshot']['content'] == CONTENT
    assert final['job']['taskOutcome']['state'] == 'completed'
    assert model.calls == 1 and len(model.reviews) == 0
