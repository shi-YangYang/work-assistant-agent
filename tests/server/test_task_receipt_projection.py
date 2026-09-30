"""Regressions from real multi-turn confirmation and team deadline journeys."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.actions.operations import execute
from app.agent.tools.team import query_team_business, read_team_source
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkRevision
from app.tasks.feedback.outcomes import derive
from app.tasks.models import Job
from test_business_actions import create, read_work, runtime
from test_conversation_task_state import close_task


pytestmark = pytest.mark.asyncio


async def test_message_and_feedback_use_frozen_receipts_without_future_confirmation_cards(setup):
    _, sessions, _, clients = setup
    first, sent = await runtime(setup, '创建选择验证甲')
    saved = await execute(first, step=1, action='create_work', changes={'title': '选择验证甲'})
    await close_task(first)
    second, newer = await runtime(setup, '删除选择验证甲')
    await read_work(second, saved['objectId'])
    deletion = await execute(second, step=1, action='delete_work', target_id=saved['objectId'], expected_revision=1)
    assert deletion['state'] == 'pending'
    await close_task(second, state='needs_confirmation')
    # Seed the durable continuation shape observed in the real UI journey.
    # Only the later message knew about the pending deletion when it was frozen.
    async with sessions.begin() as db:
        earlier = await db.get(Job, first.job_id)
        later = await db.get(Job, second.job_id)
        task_id = earlier.result['taskSnapshot']['taskId']
        earlier.result = {**earlier.result, 'taskSnapshot': {**earlier.result['taskSnapshot'], 'relation': 'continue'}}
        later.result = {**later.result, 'taskSnapshot': {**later.result['taskSnapshot'], 'taskId': task_id, 'relation': 'continue', 'previousTask': {'items': earlier.result['taskItems']}}}
        (await db.get(BusinessAction, deletion['id'])).task_id = task_id
    for endpoint in ('messages/{messageId}', 'jobs/{jobId}/feedback'):
        original = await clients['employee'].get('/api/v1/' + endpoint.format(**sent))
        assert original.status_code == 200, original.text
        data = original.json()
        assert [card['id'] for card in data['actions']] == [saved['id']]
        outcome = data['job']['taskOutcome'] if 'job' in data else data['taskOutcome']
        assert outcome['state'] == 'completed' and outcome['nextAction'] == 'none'
        continued = (await clients['employee'].get('/api/v1/' + endpoint.format(**newer))).json()
        assert {card['id'] for card in continued['actions']} == {saved['id'], deletion['id']}
        outcome = continued['job']['taskOutcome'] if 'job' in continued else continued['taskOutcome']
        assert outcome['nextAction'] == 'confirm'
    cancelled = await clients['employee'].post('/api/v1/business-actions/' + deletion['id'] + '/cancel', json={'expectedRevision': deletion['revision']})
    assert cancelled.status_code == 200 and cancelled.json()['state'] == 'cancelled'
    after = (await clients['employee'].get('/api/v1/messages/' + newer['messageId'])).json()
    assert after['job']['taskOutcome']['state'] == 'completed'
    assert after['job']['taskOutcome']['remaining'] == []
    assert after['job']['taskOutcome']['nextAction'] == 'none'
    work = (await clients['employee'].get('/api/v1/work-items/' + saved['objectId'])).json()
    assert work['title'] == '选择验证甲' and work['revision'] == 1


@pytest.mark.parametrize('other_state, expected, next_action', [
    (None, 'cancelled', 'none'),
    ('succeeded', 'completed', 'none'),
    ('pending', 'needs_confirmation', 'confirm'),
])
async def test_cancelled_action_is_not_an_unfinished_request(other_state, expected, next_action):
    job = SimpleNamespace(state='succeeded', result={'taskInterpretation': {'state': 'needs_confirmation', 'remaining': ['等待确认']}}, error='')
    cards = [{'state': 'cancelled', 'label': '删除工作', 'title': '选择验证甲'}]
    if other_state:
        cards.append({'state': other_state, 'label': '更新工作', 'title': '选择验证乙'})
    outcome = derive(job, cards)
    assert outcome['state'] == expected and outcome['nextAction'] == next_action
    assert not any('选择验证甲' in item for item in outcome['remaining'])
    # A cancelled report child remains a genuine interrupted generation.
    report = derive(job, [{'state': 'running', 'label': '生成报告', 'job': {'state': 'cancelled'}}])
    assert report['state'] == 'cancelled' and report['reason'] == '报告生成已中断。'


async def test_team_tools_preserve_versioned_deadline_even_when_content_is_clipped(setup):
    _, sessions, users, clients = setup
    work = await create(clients['employee'], '培训安排', dueDate='2026-10-09', status='blocked', summary='待协调讲师时间。' * 100)
    updated = await clients['employee'].post('/api/v1/work-items/' + work['id'] + '/progress', json={'title': '培训安排', 'dueDate': '2026-10-12', 'status': 'in_progress', 'expectedRevision': 1})
    assert updated.status_code == 200, updated.text
    await create(clients['employee'], '未设期限')
    async with sessions.begin() as db:
        revisions = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == work['id']))).all()
        for revision in revisions:
            revision.created_at = datetime(2026, 9, 10 if revision.revision == 1 else 12, 4, tzinfo=timezone.utc)
    context, _ = await runtime(setup, '查询员工培训的期限与历史记录', who='admin')
    rt = SimpleNamespace(context=context)
    current = json.loads(await query_team_business.coroutine(rt, employee_ids=[users['employee'].id]))
    by_title = {row['title']: row for row in current['items']}
    assert by_title['培训安排']['dueDate'] == '2026-10-12'
    assert by_title['培训安排']['revision'] == 2 and by_title['培训安排']['contentTruncated']
    assert by_title['未设期限']['dueDate'] is None
    historical = json.loads(await query_team_business.coroutine(rt, employee_ids=[users['employee'].id], query='培训安排', period='custom', start='2026-09-10', end='2026-09-10'))
    assert len(historical['items']) == 1
    previous = historical['items'][0]
    assert previous['dueDate'] == '2026-10-09' and previous['revision'] == 1 and previous['currentRevision'] == 2
    details = json.loads(await read_team_source.coroutine(previous['token'], rt))
    assert details['dueDate'] == '2026-10-09' and details['content']['status'] == 'blocked'
    assert details['citation'] == previous['citation']
