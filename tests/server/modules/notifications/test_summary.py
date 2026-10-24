from datetime import timedelta
import pytest
from app.db.base import now
from app.modules.announcements.models import Announcement
from app.modules.reports.models import ReportObligation, ReportNotification


@pytest.mark.asyncio
async def test_summary_reuses_pending_personal_reminders_without_session_renewal(setup):
    _, sessions, users, clients = setup
    async with sessions.begin() as db:
        for index, (owner, state, read) in enumerate([('employee', 'pending', False), ('employee', 'pending', True), ('employee', 'submitted', False), ('peer', 'pending', False)]):
            member = users[owner]
            obligation = ReportObligation(company_id=member.company_id, owner_id=member.id, kind='weekly', period=f'2026-10-{index+1:02}', period_end=f'2026-10-{index+1:02}', timezone='Asia/Shanghai', rule_revision=1, generate_at=now(), deadline_at=now()+timedelta(hours=1), reminders=True, before_minutes=60, state=state)
            db.add(obligation); await db.flush()
            db.add(ReportNotification(company_id=member.company_id, owner_id=member.id, obligation_id=obligation.id, stage='due', read_at=now() if read else None))
        db.add(Announcement(company_id=users['admin'].company_id, title='通知', markdown='内容', author_id=users['admin'].id, author_name='管理员', editor_id=users['admin'].id, editor_name='管理员'))
    response = await clients['employee'].get('/api/v1/notification-summary')
    assert response.json() == {'remindersUnread': 1, 'announcementsUnread': 1, 'totalUnread': 2}
    assert 'set-cookie' not in response.headers
    legacy = (await clients['employee'].get('/api/v1/notifications')).json()
    assert legacy['unread'] == 1 and len(legacy['items']) == 2
    assert (await clients['admin'].get('/api/v1/notification-summary')).json() == {'remindersUnread': 0, 'announcementsUnread': 1, 'totalUnread': 1}
    assert (await clients['admin'].get('/api/v1/notifications')).json()['items'] == []
    identifier = next(item['id'] for item in legacy['items'] if not item['read'])
    await clients['employee'].post(f'/api/v1/notifications/{identifier}/read')
    assert (await clients['employee'].get('/api/v1/notification-summary')).json()['totalUnread'] == 1
