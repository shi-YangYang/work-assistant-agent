"""Operation dependencies stay current without treating all chat history as one."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.actions.operations import execute
from app.agent.context.history import conversation_history
from app.agent.tools.team import query_team_business
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem, WorkRevision
from app.tasks.models import Job
from test_business_actions import create, read_work, runtime
from test_conversation_task_state import ScopedJudge, close_task

pytestmark = pytest.mark.asyncio


async def query_source(context, employee, title):
    response = json.loads(await query_team_business.coroutine(
        SimpleNamespace(context=context), employee_ids=[employee.id], query=title))
    assert len(response['items']) == 1, response
    return response['items'][0]['token']


async def linked_work(setup):
    _, sessions, users, clients = setup
    source = await create(clients['employee'], '培训安排', dueDate='2026-10-09', status='blocked', summary='讲师时间待协调')
    context, sent = await runtime(setup, '把培训协调加入我的工作，截止9月30日', 'admin')
    token = await query_source(context, users['employee'], source['title'])
    result = await execute(context, step=1, action='create_work', changes={
        'title': '协调培训', 'summary': '培训未设置截止日期', 'dueDate': '2026-09-30',
        'status': 'in_progress', 'blocker': '', 'nextStep': '联系讲师'}, source_tokens=[token])
    assert result['state'] == 'succeeded', result
    return context, sent, source, result['objectId'], token


async def update_source(client, source):
    response = await client.post('/api/v1/work-items/' + source['id'] + '/progress', json={
        'title': source['title'], 'summary': '材料已更新', 'dueDate': '2026-10-12', 'expectedRevision': source['revision']})
    assert response.status_code == 200, response.text
    return response.json()


async def test_unrelated_historical_revision_does_not_block_current_work_correction(setup):
    _, sessions, users, clients = setup
    first, sent, source, identifier, token = await linked_work(setup)
    unrelated = await create(clients['employee'], '书店方案', summary='旧版资料')
    old_token = await query_source(first, users['employee'], unrelated['title'])
    # Persist the first turn's actual query scope as the ordinary worker does.
    async with sessions.begin() as db:
        job = await db.get(Job, first.job_id)
        message = await db.get(Message, sent['messageId'])
        message.access, message.reply = job.access, '培训和书店资料已查询。'
    await close_task(first)
    await update_source(clients['employee'], unrelated)

    context, newer = await runtime(setup, '只纠正培训截止日期说明，保留我的协调期限和其他字段', 'admin')
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
    await conversation_history(context, job, '只纠正培训截止日期说明')
    await read_work(context, identifier)
    current_token = await query_source(context, users['employee'], source['title'])
    assert current_token == token
    result = await execute(context, step=1, action='update_work', target_id=identifier,
                           expected_revision=1, changes={'summary': '培训截止日期为2026-10-09'}, source_tokens=[current_token])
    assert result['state'] == 'succeeded', result
    after = (await clients['admin'].get('/api/v1/work-items/' + identifier)).json()
    assert after['summary'] == '培训截止日期为2026-10-09' and after['revision'] == 2
    assert after['dueDate'] == '2026-09-30' and after['status'] == 'in_progress'
    assert after['nextStep'] == '联系讲师' and after['blocker'] == ''
    async with sessions() as db:
        receipt = await db.get(BusinessAction, result['id'])
        saved = await db.get(WorkItem, identifier)
        assert old_token in receipt.access['reads'] and old_token in saved.access['reads']
        assert receipt.access['reads'][old_token]['version'] == 1
        assert (await db.get(WorkItem, source['id'])).revision == 1
        assert len((await db.scalars(select(WorkRevision).where(WorkRevision.work_id == identifier))).all()) == 2
    # The change does not erase historical restrictions or rewrite old evidence.
    old = await clients['admin'].get(f"/api/v1/business-sources/{sent['messageId']}/{old_token}")
    assert old.status_code == 200 and old.json()['revision'] == 1 and old.json()['currentRevision'] == 2
    async with sessions.begin() as db:
        (await db.get(Member, users['admin'].id)).role = 'employee'
    assert (await clients['admin'].get('/api/v1/work-items/' + identifier)).status_code == 403


@pytest.mark.parametrize('select_new_source', [False, True])
async def test_existing_followup_requires_fresh_source_even_if_tokens_are_omitted(setup, select_new_source):
    _, sessions, users, clients = setup
    first, _, source, identifier, old_token = await linked_work(setup)
    await close_task(first)
    await update_source(clients['employee'], source)
    context, _ = await runtime(setup, '按最新培训截止日期修正我的协调说明', 'admin')
    await read_work(context, identifier)
    current_token = await query_source(context, users['employee'], source['title'])
    assert current_token != old_token
    result = await execute(context, step=1, action='update_work', target_id=identifier,
                           expected_revision=1, changes={'summary': '培训截止日期为2026-10-12'},
                           source_tokens=[current_token] if select_new_source else [])
    assert result['state'] == ('succeeded' if select_new_source else 'conflict'), result
    after = (await clients['admin'].get('/api/v1/work-items/' + identifier)).json()
    assert after['revision'] == (2 if select_new_source else 1)
    assert after['summary'] == ('培训截止日期为2026-10-12' if select_new_source else '培训未设置截止日期')
    assert after['dueDate'] == '2026-09-30'
    if select_new_source:
        async with sessions() as db:
            saved = await db.get(WorkItem, identifier)
            assert {link['token'] for link in saved.business_links} == {old_token, current_token}
        await close_task(context)
        third, _ = await runtime(setup, '给协调工作补充下一步：明天联系讲师', 'admin')
        await read_work(third, identifier)
        next_result = await execute(third, step=1, action='update_work', target_id=identifier,
                                    expected_revision=2, changes={'nextStep': '明天联系讲师'})
        assert next_result['state'] == 'succeeded', next_result
        final = (await clients['admin'].get('/api/v1/work-items/' + identifier)).json()
        assert final['revision'] == 3 and final['nextStep'] == '明天联系讲师'
        assert final['summary'] == after['summary'] and final['dueDate'] == '2026-09-30'


@pytest.mark.parametrize('change', ['revision', 'delete', 'role'])
async def test_confirmation_rechecks_selected_source_and_permissions_before_writing(setup, change):
    _, sessions, users, clients = setup
    source = await create(clients['employee'], '待确认培训', dueDate='2026-10-09')
    context, _ = await runtime(setup, '先让我确认再创建关联培训督办', 'admin')
    context.intent_model = ScopedJudge(preview=True)
    token = await query_source(context, users['employee'], source['title'])
    result = await execute(context, step=1, action='create_work', changes={'title': '待确认协调'}, source_tokens=[token])
    assert result['state'] == 'pending', result
    await close_task(context, state='needs_confirmation')
    if change == 'revision':
        await update_source(clients['employee'], source)
    elif change == 'delete':
        response = await clients['employee'].request('DELETE', '/api/v1/work-items/' + source['id'], json={'expectedRevision': 1})
        assert response.status_code == 200, response.text
    else:
        async with sessions.begin() as db:
            (await db.get(Member, users['admin'].id)).role = 'employee'
    response = await clients['admin'].post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
    assert response.status_code == (409 if change == 'revision' else 403), response.text
    async with sessions() as db:
        action = await db.get(BusinessAction, result['id'])
        assert action.state == 'pending' and action.revision == result['revision']
        assert not (await db.scalars(select(WorkItem).where(WorkItem.owner_id == users['admin'].id))).all()
