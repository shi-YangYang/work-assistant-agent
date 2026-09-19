from datetime import datetime, timedelta, timezone

import pytest

from paa_server.models import Report, ReportObligation, ReportRevision
from test_search_metrics_feedback import content, work

pytestmark = pytest.mark.asyncio
DAY = datetime(2026, 9, 12, 6, tzinfo=timezone.utc)
RANGE = {'period': 'custom', 'start': '2026-09-12', 'end': '2026-09-12'}


async def test_current_blockers_and_historical_updates_keep_scope_and_permissions(setup):
    _, sessions, users, clients = setup
    async with sessions.begin() as db:
        old = await work(db, users['employee'], content('旧阻碍', 'blocked', '未解决'), DAY - timedelta(days=30))
        changed = await work(db, users['employee'], content('历史阻碍', 'blocked', '待确认'), DAY)
        changed.content = content('现在完成', 'done')
        changed.title, changed.revision, changed.updated_at = '现在完成', 2, DAY + timedelta(days=2)
        from paa_server.models import WorkRevision
        db.add(WorkRevision(company_id=changed.company_id, owner_id=changed.owner_id, work_id=changed.id, revision=2, content=changed.content, source_ids=[], created_at=changed.updated_at))
        for role in ('admin', 'outsider'):
            await work(db, users[role], content('不可出现在员工看板', 'blocked'), DAY)
        await work(db, users['employee'], content('受限来源'), DAY, access={'team': True, 'actorId': users['peer'].id, 'companyId': users['peer'].company_id})
    client = clients['admin']
    data = (await client.get('/api/v1/team/workspace/work', params={**RANGE, 'status': 'blocked'})).json()
    assert [r['id'] for r in data['items']] == [old.id]
    assert data['counts'] == {'all': 2, 'in_progress': 1, 'blocked': 1, 'done': 1}
    history = (await client.get('/api/v1/team/workspace/work', params={**RANGE, 'scope': 'updated', 'status': 'blocked'})).json()
    assert [r['id'] for r in history['items']] == [changed.id]
    assert history['items'][0]['work']['revision'] == 1
    assert history['items'][0]['work']['title'] == '历史阻碍'
    detail = (await client.get(f'/api/v1/work-items/{changed.id}?revision=1')).json()
    assert detail['summary'] == history['items'][0]['work']['summary']
    for view in ('work', 'reports'):
        assert (await clients['employee'].get('/api/v1/team/workspace/' + view)).status_code == 403
        hidden = (await client.get('/api/v1/team/workspace/' + view, params={**RANGE, 'member': users['outsider'].id})).json()
        assert hidden['total'] == 0


async def report(db, actor, period, *, published=True):
    public = {'completed': '已提交内容', 'ongoing': '', 'blockers': '', 'next': ''}
    row = Report(company_id=actor.company_id, owner_id=actor.id, kind='daily', period=period, period_end=period, timezone='Asia/Shanghai', content={'completed': '不能泄露的后续草稿'}, revision=2, published_revision=1 if published else 0)
    db.add(row)
    await db.flush()
    if published:
        db.add(ReportRevision(company_id=row.company_id, owner_id=row.owner_id, report_id=row.id, revision=1, content=public, source_ids=[], created_at=DAY + timedelta(days=5)))
    return row


async def test_reports_merge_schedule_and_manual_submission_without_exposing_drafts(setup):
    _, sessions, users, clients = setup
    async with sessions.begin() as db:
        employee = users['employee']
        submitted = await report(db, employee, '2026-09-12')
        draft = await report(db, users['peer'], '2026-09-12', published=False)
        await report(db, users['outsider'], '2026-09-12')
        await report(db, users['admin'], '2026-09-12')
        db.add(ReportObligation(company_id=employee.company_id, owner_id=employee.id, kind='daily', period='2026-09-11', period_end='2026-09-12', timezone='Asia/Shanghai', rule_revision=1, generate_at=DAY, deadline_at=DAY, reminders=False, before_minutes=0, state='cancelled'))
        db.add(ReportObligation(company_id=draft.company_id, owner_id=draft.owner_id, kind='daily', period=draft.period, period_end=draft.period_end, timezone='Asia/Shanghai', rule_revision=1, generate_at=DAY, deadline_at=DAY + timedelta(hours=2), reminders=False, before_minutes=0, state='pending', report_id=draft.id))
    client = clients['admin']
    data = (await client.get('/api/v1/team/workspace/reports', params=RANGE)).json()
    assert data['counts'] == {'all': 2, 'cancelled': 1, 'expected': 1, 'submitted': 1, 'pending': 1, 'overdue': 1}
    assert '不能泄露' not in str(data) and draft.id not in str(data)
    assert {r['member']['id'] for r in data['items']} == {users['employee'].id, users['peer'].id}
    published = next(r for r in data['items'] if r['state'] == 'submitted')
    assert published['reportId'] == submitted.id and published['summary'] == '已提交内容'
    assert not published['scheduled']
    detail = (await client.get(f'/api/v1/reports/{submitted.id}?revision=1')).json()
    assert detail['content']['completed'] == published['summary']
    assert detail['ownerName'] == employee.name
    for status, total in [('submitted', 1), ('expected', 1), ('pending', 1), ('overdue', 1), ('cancelled', 1)]:
        filtered = (await client.get('/api/v1/team/workspace/reports', params={**RANGE, 'status': status})).json()
        assert filtered['total'] == total and filtered['counts'] == data['counts']
    async with sessions.begin() as db:
        db.add(ReportObligation(company_id=submitted.company_id, owner_id=submitted.owner_id, kind='daily', period=submitted.period, period_end=submitted.period_end, timezone='Asia/Shanghai', rule_revision=1, generate_at=DAY, deadline_at=DAY, reminders=False, before_minutes=0, state='submitted', report_id=submitted.id, submitted_at=DAY))
    merged = (await client.get('/api/v1/team/workspace/reports', params=RANGE)).json()
    assert merged['total'] == 2 and merged['counts']['expected'] == 2


async def test_workspace_search_and_pagination_cover_all_rows(setup):
    _, sessions, users, clients = setup
    async with sessions.begin() as db:
        for index in range(23):
            await work(db, users['employee'], content(f'方案 {index}'), DAY + timedelta(minutes=index))
            await report(db, users['employee'], (DAY + timedelta(days=index)).date().isoformat())
    for view in ('work', 'reports'):
        filters = {'period': 'custom', 'start': '2026-09-01', 'end': '2026-10-31'}
        first = (await clients['admin'].get('/api/v1/team/workspace/' + view, params=filters)).json()
        second = (await clients['admin'].get('/api/v1/team/workspace/' + view, params={**filters, 'offset': first['nextCursor']})).json()
        assert first['total'] == second['total'] == 23
        assert len(first['items']) == 20 and len(second['items']) == 3 and second['nextCursor'] is None
        assert len({r['id'] for r in first['items'] + second['items']}) == 23
    search = (await clients['admin'].get('/api/v1/team/workspace/work', params={'q': '方案 0'})).json()
    assert search['total'] == 1
