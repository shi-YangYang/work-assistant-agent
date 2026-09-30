"""HTTP/DB checks for Web request branches absent from the existing regression suite."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.reports.models import Report
from app.modules.work.models import ProgressDraft, WorkItem
from app.security.access import receipt, remember
from test_business_assistant import facts
from test_company import keyed
from test_management import conversation

pytestmark = pytest.mark.asyncio


async def test_orphan_action_query_keeps_missing_and_deleted_sources_in_own_conversation(setup):
    _, sessions, users, clients = setup
    actor = users['employee']
    selected = await conversation(clients['employee'])
    other = await conversation(clients['employee'])
    async with sessions.begin() as db:
        visible = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=selected['id'], text='仍在历史中')
        removed = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=selected['id'], text='已删除来源', deleted=True)
        db.add_all([visible, removed])
        await db.flush()
        rows = []
        for source_id, conversation_id in ((visible.id, selected['id']), (removed.id, selected['id']), (str(uuid4()), selected['id']), (str(uuid4()), other['id'])):
            row = BusinessAction(company_id=actor.company_id, owner_id=actor.id, message_id=source_id, conversation_id=conversation_id, step=1, action='delete_work', digest=uuid4().hex, intent_key=uuid4().hex, state='cancelled', access={'role': actor.role}, result={'message': '未删除工作'})
            db.add(row)
            rows.append(row)
        await db.flush()
        expected = {row.id for row in rows[1:3]}
    endpoint = '/api/v1/business-actions'
    query = {'conversationId': selected['id'], 'orphanOnly': 'true'}
    response = await clients['employee'].get(endpoint, params=query)
    assert response.status_code == 200
    assert {item['id'] for item in response.json()['items']} == expected
    assert all(item['state'] == 'cancelled' and item['message'] == '未删除工作' for item in response.json()['items'])
    full = await clients['employee'].get(endpoint, params={'conversationId': selected['id']})
    assert {item['id'] for item in full.json()['items']} == {row.id for row in rows[:3]}
    for who in ('admin', 'peer', 'outsider'):
        assert (await clients[who].get(endpoint, params=query)).status_code == 404
    async with sessions.begin() as db:
        (await db.get(Conversation, selected['id'])).deleted = True
    assert (await clients['employee'].get(endpoint, params=query)).status_code == 404


async def test_ignore_progress_drafts_is_atomic_versioned_private_and_replay_safe(setup):
    _, sessions, users, clients = setup
    actor = users['employee']
    async with sessions.begin() as db:
        source = Message(company_id=actor.company_id, owner_id=actor.id, text='待决定的工作建议')
        db.add(source)
        await db.flush()
        drafts = [ProgressDraft(company_id=actor.company_id, owner_id=actor.id, message_id=source.id, content={'title': title}, tool_key=uuid4().hex) for title in ('第一项', '第二项')]
        db.add_all(drafts)
        await db.flush()
        items = [{'id': draft.id, 'expectedRevision': draft.revision} for draft in drafts]
    endpoint = '/api/v1/progress-drafts/ignore'
    for who in ('admin', 'peer', 'outsider'):
        assert (await clients[who].post(endpoint, json={'items': items}, headers=keyed())).status_code == 404
    stale = [items[0], {**items[1], 'expectedRevision': 99}]
    assert (await clients['employee'].post(endpoint, json={'items': stale}, headers=keyed())).status_code == 409
    async with sessions() as db:
        states = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == source.id))).all()
        assert {(draft.status, draft.revision) for draft in states} == {('pending', 1)}
    headers = keyed()
    first = await clients['employee'].post(endpoint, json={'items': items}, headers=headers)
    replay = await clients['employee'].post(endpoint, json={'items': items}, headers=headers)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json() == {'workIds': []}
    assert (await clients['employee'].post(endpoint, json={'items': items}, headers=keyed())).status_code == 409
    async with sessions() as db:
        states = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == source.id))).all()
        assert {(draft.status, draft.revision) for draft in states} == {('ignored', 2)}
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == actor.id)) == 0


async def test_adopt_report_candidate_updates_real_content_sources_and_rejects_stale_or_foreign_writes(setup):
    _, sessions, users, clients = setup
    actor = users['employee']
    _, revision, _ = await facts(sessions, actor)
    original = {'completed': '原稿', 'ongoing': '', 'blockers': '', 'next': ''}
    candidate = {**original, 'completed': '候选版本的真实内容'}
    async with sessions.begin() as db:
        report = Report(company_id=actor.company_id, owner_id=actor.id, kind='daily', period='2026-09-29', period_end='2026-09-29', timezone='Asia/Shanghai', content=original, candidate={'content': candidate, 'sourceIds': [revision.id]})
        db.add(report)
        await db.flush()
    endpoint = f'/api/v1/reports/{report.id}/candidate'
    for who, status in (('admin', 403), ('peer', 404), ('outsider', 404)):
        assert (await clients[who].post(endpoint, json={'expectedRevision': 1})).status_code == status
    assert (await clients['employee'].post(endpoint, json={'expectedRevision': 99})).status_code == 409
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        assert saved.content == original and saved.revision == 1 and saved.candidate
    result = await clients['employee'].post(endpoint, json={'expectedRevision': 1})
    assert result.status_code == 200
    assert result.json()['content'] == candidate and result.json()['revision'] == 2
    assert result.json()['candidate'] is None
    assert (await clients['employee'].post(endpoint, json={'expectedRevision': 2})).status_code == 409
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        assert saved.content == candidate and saved.source_ids == [revision.id]
        assert saved.candidate is None and saved.edited and saved.published_revision == 0
        assert saved.revision == 2


async def test_work_business_source_keeps_historical_evidence_and_rechecks_access(setup):
    _, sessions, users, clients = setup
    source, revision, _ = await facts(sessions, users['employee'])
    actor = users['admin']
    async with sessions.begin() as db:
        followup = WorkItem(company_id=actor.company_id, owner_id=actor.id, title='督办事项', content={'title': '督办事项'})
        evidence = receipt('work', revision)
        token = remember(followup, actor, evidence)
        followup.business_links = [{'token': token, 'evidence': evidence}]
        db.add(followup)
        await db.flush()
    endpoint = f'/api/v1/work-items/{followup.id}/business-sources/{token}'
    first = await clients['admin'].get(endpoint)
    assert first.status_code == 200
    assert first.json()['objectId'] == source.id and first.json()['revision'] == 1
    assert first.json()['content'] == revision.content
    for who in ('employee', 'peer', 'outsider'):
        assert (await clients[who].get(endpoint)).status_code == 404
    assert (await clients['admin'].get(f'/api/v1/work-items/{followup.id}/business-sources/forged')).status_code == 404
    async with sessions.begin() as db:
        current = await db.get(WorkItem, source.id)
        current.revision = 2
        current.content = {**current.content, 'summary': '新版本内容'}
    historical = await clients['admin'].get(endpoint)
    assert historical.status_code == 200
    assert historical.json()['content'] == revision.content
    assert historical.json()['currentRevision'] == 2 and historical.json()['revision'] == 1
    async with sessions.begin() as db:
        (await db.get(WorkItem, source.id)).deleted = True
    assert (await clients['admin'].get(endpoint)).status_code == 404
