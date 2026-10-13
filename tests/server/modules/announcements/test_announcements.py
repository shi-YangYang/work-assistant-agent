import asyncio
from uuid import uuid4
import pytest
from sqlalchemy import func, select
from app.modules.announcements.models import Announcement, AnnouncementRead


async def publish(client, **body):
    response = await client.post('/api/v1/announcements', json={'title': '公司公告', 'markdown': '# 事项\n请大家阅读', **body}, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_publish_replay_scope_and_read_versions(setup):
    _, sessions, users, clients = setup
    admin, employee = clients['admin'], clients['employee']
    body = {'title': ' 通知 ', 'markdown': '\r\n正文\r\n'}
    headers = {'Idempotency-Key': str(uuid4())}
    replies = await asyncio.gather(*(admin.post('/api/v1/announcements', json=body, headers=headers) for _ in range(2)))
    assert all(response.status_code == 201 for response in replies)
    assert replies[0].json() == replies[1].json()
    item = replies[0].json()
    path = '/api/v1/announcements/' + item['id']
    assert item['title'] == '通知' and item['markdown'] == '正文'
    assert (await admin.post('/api/v1/announcements', json={**body, 'title': '另一个'}, headers=headers)).status_code == 409
    assert (await employee.get('/api/v1/notification-summary')).json()['announcementsUnread'] == 1
    # Lists, details and management previews do not mark read.
    assert (await employee.get('/api/v1/announcements')).json()['items'][0]['unread']
    assert (await employee.get(path)).json()['unread']
    assert (await admin.get(path + '?management=true')).json()['unread']
    assert (await employee.get('/api/v1/notification-summary')).json()['announcementsUnread'] == 1
    for _ in range(2):
        assert (await employee.post(path + '/read', json={'expectedRevision': 1})).status_code == 200
    assert (await employee.get('/api/v1/notification-summary')).json()['announcementsUnread'] == 0
    assert (await admin.get('/api/v1/notification-summary')).json()['announcementsUnread'] == 1
    # No-op saves retain version; editing creates a new unread version.
    same = await admin.patch(path, json={'title': '通知', 'markdown': '正文\n', 'expectedRevision': 1})
    assert same.json()['revision'] == 1
    edit = await admin.patch(path, json={'title': '新通知', 'markdown': '新正文', 'expectedRevision': 1})
    assert edit.status_code == 200 and edit.json()['revision'] == 2
    assert edit.json()['publishedAt'] == item['publishedAt']
    assert (await employee.post(path + '/read', json={'expectedRevision': 1})).status_code == 409
    assert (await employee.post(path + '/read', json={'expectedRevision': 3})).status_code == 409
    assert (await employee.get('/api/v1/notification-summary')).json()['announcementsUnread'] == 1
    assert (await clients['outsider'].get(path)).status_code == 404
    assert (await clients['outsider'].post(path + '/read', json={'expectedRevision': 2})).status_code == 404
    assert (await clients['outsider'].get('/api/v1/notification-summary')).json()['totalUnread'] == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AnnouncementRead).where(AnnouncementRead.announcement_id == item['id'])) == 1


@pytest.mark.asyncio
async def test_admin_writes_csrf_version_conflict_and_idempotent_deletion(setup):
    _, sessions, users, clients = setup
    admin, employee = clients['admin'], clients['employee']
    item = await publish(admin)
    path = '/api/v1/announcements/' + item['id']
    for method, endpoint, body in [('post', '/api/v1/announcements', {'title': 'a', 'markdown': 'b'}), ('patch', path, {'title': 'a', 'markdown': 'b', 'expectedRevision': 1}), ('delete', path, {'expectedRevision': 1})]:
        assert (await employee.request(method.upper(), endpoint, json=body, headers={'Idempotency-Key': str(uuid4())})).status_code == 403
    assert (await employee.get(path + '?management=true')).status_code == 403
    assert (await employee.get('/api/v1/announcements?state=withdrawn')).status_code == 403
    assert (await admin.patch(path, json={'title': 'a', 'markdown': 'b', 'expectedRevision': 1}, headers={'X-CSRF-Token': 'wrong'})).status_code == 403
    edits = await asyncio.gather(*(admin.patch(path, json={'title': title, 'markdown': 'b', 'expectedRevision': 1}) for title in ('一', '二')))
    assert sorted(result.status_code for result in edits) == [200, 409]
    assert (await employee.post(path + '/read', json={'expectedRevision': 2})).status_code == 200
    async with sessions.begin() as db:
        from app.modules.members.models import Member
        outsider = await db.get(Member, users['outsider'].id)
        outsider.role = 'admin'
    key = {'Idempotency-Key': str(uuid4())}
    assert (await clients['outsider'].request('DELETE', path, json={'expectedRevision': 2}, headers=key)).status_code == 404
    assert (await admin.request('DELETE', path, json={'expectedRevision': 2}, headers={**key, 'X-CSRF-Token': 'wrong'})).status_code == 403
    assert (await admin.request('DELETE', path, json={'expectedRevision': 1}, headers=key)).status_code == 409
    assert (await admin.get(path + '?management=true')).status_code == 200
    deleted = await asyncio.gather(*(admin.request('DELETE', path, json={'expectedRevision': 2}, headers=key) for _ in range(2)))
    assert all(response.status_code == 200 and response.json() == {'ok': True} for response in deleted)
    assert (await employee.get(path)).status_code == 404
    assert (await admin.get(path + '?management=true')).status_code == 404
    assert (await employee.post(path + '/read', json={'expectedRevision': 2})).status_code == 404
    assert (await admin.patch(path, json={'title': 'a', 'markdown': 'b', 'expectedRevision': 2})).status_code == 404
    assert (await employee.get('/api/v1/announcements')).json()['items'] == []
    assert (await admin.get('/api/v1/announcements')).json()['items'] == []
    assert (await admin.get('/api/v1/announcements?state=withdrawn')).json()['items'] == []
    assert (await admin.get('/api/v1/notification-summary')).json()['totalUnread'] == 0
    assert (await employee.get('/api/v1/notification-summary')).json()['totalUnread'] == 0
    async with sessions() as db:
        assert await db.get(Announcement, item['id']) is None
        assert await db.scalar(select(func.count()).select_from(AnnouncementRead).where(AnnouncementRead.announcement_id == item['id'])) == 0



@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'title': '', 'markdown': 'a'}, {'title': 'a', 'markdown': '   '}, {'title': 'a'*101, 'markdown': 'a'}, {'title': 'a', 'markdown': 'a'*20001}, {'title': 'a', 'markdown': 'b', 'company_id': 'other'}])
async def test_content_validation(setup, body):
    response = await setup[3]['admin'].post('/api/v1/announcements', json=body, headers={'Idempotency-Key': str(uuid4())})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pagination_soft_reader_delete_and_author_snapshot(setup):
    _, sessions, users, clients = setup
    async with sessions.begin() as db:
        for index in range(23):
            db.add(Announcement(company_id=users['admin'].company_id, title=f'公告{index}', markdown='x'*20000,
                                author_id=users['peer'].id, author_name='原始名字', editor_id=users['admin'].id, editor_name='管理员'))
    first = (await clients['employee'].get('/api/v1/announcements')).json()
    second = (await clients['employee'].get('/api/v1/announcements?cursor=' + first['nextCursor'])).json()
    assert len(first['items']) == 20 and len(second['items']) == 3 and second['nextCursor'] is None
    assert len({item['id'] for item in first['items'] + second['items']}) == 23
    assert all('markdown' not in item and len(item['summary']) == 180 for item in first['items'])
    identifier = first['items'][0]['id']
    assert (await clients['peer'].post(f'/api/v1/announcements/{identifier}/read', json={'expectedRevision': 1})).status_code == 200
    assert (await clients['admin'].delete('/api/v1/members/' + users['peer'].id)).status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AnnouncementRead).where(AnnouncementRead.reader_id == users['peer'].id)) == 0
        assert await db.scalar(select(func.count()).select_from(Announcement).where(Announcement.company_id == users['admin'].company_id)) == 23
    assert (await clients['employee'].get(f'/api/v1/announcements/{identifier}')).json()['authorName'] == '原始名字'


def test_list_summary_is_readable_text():
    from app.modules.announcements.service import summary_text
    assert summary_text('## 时间调整\n\n- **明天** [开会](https://example.com)\n\n![图片](https://example.com/i.png)') == '时间调整 明天 开会'
