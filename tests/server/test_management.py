import asyncio
import io
import pytest
from PIL import Image
from datetime import timedelta
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.agent.checkpoints import GuardedSaver
from app.agent.history import conversation_history
from app.agent.tools.reports import draft_report
from app.db.base import now
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.reports.sources import report_inputs
from app.modules.work.models import WorkRevision
from app.tasks.context import LostLease, RunContext
from app.tasks.models import Job
from pathlib import Path
from sqlalchemy import select, text
from test_company import keyed, run_target
from types import SimpleNamespace
from uuid import uuid4

pytestmark = pytest.mark.asyncio


async def conversation(client, title='新会话'):
    response = await client.post('/api/v1/conversations', json={'title': title})
    assert response.status_code == 201
    return response.json()


async def message(client, conv, value='方案初稿完成', attachments=None, **extra):
    response = await client.post('/api/v1/messages', json={'conversationId':conv['id'], 'text':value, 'attachmentIds': attachments or [], **extra}, headers=keyed())
    assert response.status_code == 202, response.text
    return response.json()


async def remove(client, kind, item):
    return await client.request('DELETE', f"/api/v1/{kind}/{item['id']}", json={'expectedRevision': item.get('managementRevision', item['revision'])})


async def confirmed(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    conv = await conversation(client)
    raw = io.BytesIO(); Image.new('RGB', (2, 2)).save(raw, format='PNG')
    uploaded = (await client.post('/api/v1/uploads', files={'file':('sample.png',raw.getvalue(),'image/png')})).json()
    sent = await message(client, conv, attachments=[uploaded['id']])
    await run_target(settings, sessions, users, sent)
    data = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    draft = data['drafts'][0]
    response = await client.post('/api/v1/progress-drafts/confirm', json={'items':[{'id':draft['id'], 'expectedRevision':draft['revision']}]}, headers=keyed())
    work = (await client.get('/api/v1/work-items/' + response.json()['workIds'][0])).json()
    conv = (await client.get('/api/v1/conversations/' + conv['id'])).json()
    return conv, sent, uploaded, work


@pytest.mark.parametrize('role', ['admin', 'employee'])
async def test_new_chat_creates_only_on_send_without_reusing_history(setup, role):
    _, _, _, clients = setup
    client = clients[role]
    for _ in range(2):
        assert (await client.get('/api/v1/conversations')).json()['items'] == []
        assert (await client.get('/api/v1/messages')).json()['items'] == []
    empty = await client.post('/api/v1/messages', json={'newConversation': True, 'text': '  '}, headers=keyed())
    assert empty.status_code == 422
    assert (await client.get('/api/v1/conversations')).json()['items'] == []

    async def send_new(value):
        payload = {'newConversation': True, 'text': value}
        headers = keyed()
        first, retry = await asyncio.gather(*[
            client.post('/api/v1/messages', json=payload, headers=headers) for _ in range(2)
        ])
        assert first.status_code == retry.status_code == 202
        assert first.json() == retry.json()
        return first.json()

    old = await send_new('历史会话的消息')
    sent = await send_new('全新会话的第一条消息')
    assert sent['conversationId'] != old['conversationId']
    rows = (await client.get('/api/v1/conversations')).json()['items']
    assert len(rows) == 2
    for item in (old, sent):
        messages = (await client.get('/api/v1/messages', params={'conversationId': item['conversationId']})).json()['items']
        assert [m['id'] for m in messages] == [item['messageId']]
    conv = next(row for row in rows if row['id'] == sent['conversationId'])
    assert conv['title'] == '全新会话的第一条消息'
    followup = await message(client, conv, '同一会话的后续消息')
    assert followup['conversationId'] == sent['conversationId']

    invalid = await client.post('/api/v1/messages', json={'newConversation': True, 'text': '附件不可用', 'attachmentIds': [str(uuid4())]}, headers=keyed())
    assert invalid.status_code == 404
    conflict = await client.post('/api/v1/messages', json={'newConversation': True, 'conversationId': old['conversationId'], 'text': '矛盾的目标'}, headers=keyed())
    assert conflict.status_code == 422
    assert len((await client.get('/api/v1/conversations')).json()['items']) == 2
    assert (await clients['outsider'].get('/api/v1/conversations/' + sent['conversationId'])).status_code == 404


async def test_conversation_crud_reply_scope_history_and_empty_delete(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    first, second, empty = [await conversation(client, name) for name in ('客户甲', '客户乙', '空会话')]
    old = await message(client, first, '甲会话的私有闲聊')
    current = await message(client, second, '乙会话的新消息')
    bad = await client.post('/api/v1/messages', json={'conversationId':second['id'], 'text':'伪造回复', 'replyTo':old['messageId']}, headers=keyed())
    assert bad.status_code == 422
    for viewer in ('peer', 'outsider', 'admin'):
        assert (await clients[viewer].get('/api/v1/conversations/' + first['id'])).status_code == 404
    assert (await client.get('/api/v1/conversations?q=客户甲')).json()['items'][0]['id'] == first['id']
    rename = await client.patch('/api/v1/conversations/' + first['id'], json={'title':'改名', 'expectedRevision':first['revision']})
    assert rename.status_code == 200
    assert (await client.patch('/api/v1/conversations/' + first['id'], json={'title':'覆盖', 'expectedRevision':first['revision']})).status_code == 409
    assert (await remove(client, 'conversations', empty)).status_code == 200
    async with sessions.begin() as db:
        job = await db.get(Job, current['jobId'])
        assert job.state == 'queued'
        job.state, job.fence, job.lease_until = 'running', 1, now() + timedelta(seconds=90)
    context = RunContext(users['employee'].id, users['employee'].company_id, job.id, job.fence, sessions, settings)
    history = await conversation_history(context, job, '新消息')
    assert not history
    assert [m['id'] for m in (await client.get('/api/v1/messages?conversationId=' + first['id'])).json()['items']] == [old['messageId']]


async def test_report_delete_purges_actual_sources_and_preserves_shared_snapshots(setup):
    settings, sessions, users, clients = setup
    conv, sent, uploaded, work = await confirmed(setup)
    actor = users['employee']
    async with sessions.begin() as db:
        source = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))
        rows = []
        for kind in ('daily', 'weekly'):
            report = Report(company_id=actor.company_id, owner_id=actor.id, kind=kind, period='2026-09-13', period_end='2026-09-13', timezone='Asia/Shanghai', content={'completed':'已确认摘要','ongoing':'','blockers':'','next':''}, source_ids=[source.id], published_revision=1)
            db.add(report); await db.flush()
            db.add(ReportRevision(company_id=actor.company_id, owner_id=actor.id, report_id=report.id, revision=1, content=report.content, source_ids=report.source_ids))
            rows.append(report)
    report = (await clients['employee'].get('/api/v1/reports/' + rows[0].id)).json()
    assert (await remove(clients['employee'], 'reports', report)).status_code == 403
    edited = await clients['employee'].patch('/api/v1/reports/' + rows[0].id, json={'expectedRevision':1,'content':{**report['content'],'ongoing':'未提交更正'}})
    assert edited.status_code == 200
    assert (await remove(clients['employee'], 'reports', edited.json())).status_code == 403
    assert (await remove(clients['outsider'], 'reports', edited.json())).status_code == 404
    assert (await remove(clients['admin'], 'reports', edited.json())).status_code == 200
    assert (await remove(clients['admin'], 'reports', edited.json())).status_code == 200
    assert not (settings.media_dir / uploaded['id']).exists()
    assert (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404
    assert (await clients['admin'].get(uploaded['url'])).status_code == 404
    assert (await clients['employee'].get('/api/v1/reports/' + rows[0].id)).status_code == 404
    other = (await clients['admin'].get('/api/v1/reports/' + rows[1].id)).json()
    assert other['content']['completed'] == '已确认摘要'
    sources = (await clients['admin'].get('/api/v1/reports/' + rows[1].id + '/sources')).json()['items']
    assert sources[0]['deletedSourceIds'] == [sent['messageId']]
    assert (await clients['employee'].get('/api/v1/work-items/' + work['id'])).status_code == 200
    assert (await clients['employee'].post('/api/v1/reports/generate', json={'kind':'daily','date':'2026-09-13'}, headers=keyed())).status_code == 409
    async with sessions() as db:
        original = await db.get(Message, sent['messageId'])
        assert original.deleted and not any([original.text,original.reply,original.transcript,original.transcript_history,original.suggestions])
        assert not await db.scalar(text('SELECT COUNT(*) FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix':actor.company_id + ':' + actor.id + ':%'})


async def test_candidate_sources_invalidate_open_delete_confirmation(setup):
    settings, sessions, users, clients = setup
    conv, first, _, work = await confirmed(setup)
    raw = io.BytesIO(); Image.new('RGB', (2, 2)).save(raw, format='PNG')
    uploaded = (await clients['employee'].post('/api/v1/uploads', files={'file': ('source-b.png', raw.getvalue(), 'image/png')})).json()
    second = await message(clients['employee'], conv, '后来新增的来源 B', attachments=[uploaded['id']])
    actor = users['employee']
    async with sessions.begin() as db:
        first_revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))
        second_revision = WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work['id'], revision=2, content=first_revision.content, source_ids=[second['messageId']])
        db.add(second_revision); await db.flush()
        report = Report(company_id=actor.company_id, owner_id=actor.id, kind='daily', period='2026-09-13', period_end='2026-09-13', timezone='Asia/Shanghai', content={'completed':'来源 A','ongoing':'','blockers':'','next':''}, source_ids=[first_revision.id], published_revision=1)
        db.add(report); await db.flush()
        db.add(ReportRevision(company_id=actor.company_id, owner_id=actor.id, report_id=report.id, revision=1, content=report.content, source_ids=report.source_ids))
        job = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=report.id, base_revision=1, state='running', fence=1, lease_until=now() + timedelta(seconds=90), result={'sourceIds': [first_revision.id, second_revision.id]})
        db.add(job); await db.flush()
    impact_path = '/api/v1/reports/' + report.id + '/deletion'
    before = (await clients['admin'].get(impact_path)).json()
    assert before['messages'] == 1
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings)
    await draft_report.coroutine(completed='来源 A 和 B', ongoing='', blockers='', next='', runtime=SimpleNamespace(context=context))
    after = (await clients['admin'].get(impact_path)).json()
    assert after['messages'] == 2 and after['revision'] == before['revision'] + 1
    stale_delete = await clients['admin'].request('DELETE', '/api/v1/reports/' + report.id, json={'expectedRevision': before['revision']})
    assert stale_delete.status_code == 409
    assert (await clients['employee'].get('/api/v1/messages/' + first['messageId'])).status_code == 200
    retained = await clients['employee'].get('/api/v1/messages/' + second['messageId'])
    assert retained.status_code == 200 and retained.json()['text'] == '后来新增的来源 B'
    assert (await clients['employee'].get(uploaded['url'])).status_code == 200
    assert (settings.media_dir / uploaded['id']).is_file()
    assert (await clients['admin'].get('/api/v1/reports/' + report.id)).status_code == 200


async def test_conversation_delete_retains_business_source_and_blocks_late_checkpoint(setup):
    settings, sessions, users, clients = setup
    conv, sent, _, work = await confirmed(setup)
    loose = await message(clients['employee'], conv, '没有确认的闲聊')
    async with sessions.begin() as db:
        job = await db.get(Job, loose['jobId'])
        job.state, job.fence, job.lease_until = 'running', 1, now() + timedelta(seconds=90)
    context = RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,settings)
    impact = (await clients['employee'].get('/api/v1/conversations/' + conv['id'] + '/deletion')).json()
    assert impact == {'messages':2,'retainedSources':1}
    assert (await remove(clients['employee'],'conversations',conv)).status_code == 200
    assert (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).status_code == 200
    assert (await clients['employee'].get('/api/v1/messages/' + loose['messageId'])).status_code == 404
    assert not (await clients['employee'].get('/api/v1/messages')).json()['items']
    assert (await clients['employee'].post('/api/v1/messages',json={'conversationId':conv['id'],'text':'恢复'},headers=keyed())).status_code == 404
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        with pytest.raises(LostLease):
            await GuardedSaver(saver,context).aput_writes({'configurable':{'thread_id':'never-created','checkpoint_id':'none'}}, [('messages','deleted raw')], 'late')
    assert (await clients['employee'].get('/api/v1/work-items/' + work['id'])).status_code == 200


async def test_cleanup_failure_is_retryable_and_work_delete_does_not_delete_sources(setup, monkeypatch):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    raw = io.BytesIO(); Image.new('RGB',(2,2)).save(raw,format='PNG')
    uploaded = (await clients['employee'].post('/api/v1/uploads',files={'file':('sample.png',raw.getvalue(),'image/png')})).json()
    sent = await message(clients['employee'],conv,attachments=[uploaded['id']])
    conv = (await clients['employee'].get('/api/v1/conversations/' + conv['id'])).json()
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path.name == uploaded['id']: raise PermissionError('controlled file lock')
        return original(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'unlink',fail)
        response = await remove(clients['employee'],'conversations',conv)
        assert response.status_code == 503 and response.json()['error']['code'] == 'cleanup_pending'
    assert (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404
    assert (await remove(clients['employee'],'conversations',conv)).status_code == 200
    assert not (settings.media_dir / uploaded['id']).exists()
    _, sent, _, work = await confirmed(setup)
    async with sessions.begin() as db:
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))
        pending = Job(owner_id=users['employee'].id,company_id=users['employee'].company_id,kind='report',target_id=str(uuid4()),result={'sourceIds':[revision.id]})
        db.add(pending); await db.flush()
    assert (await remove(clients['employee'],'work-items',work)).status_code == 200
    async with sessions() as db:
        assert (await db.get(Job,pending.id)).state == 'cancelled'
    assert (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).status_code == 200
    assert not (await clients['employee'].get('/api/v1/work-items')).json()['items']
    async with sessions() as db:
        report = Report(owner_id=users['employee'].id, company_id=users['employee'].company_id, timezone='Asia/Shanghai',period='2000-01-01',period_end='2099-01-01')
        assert not await report_inputs(db,report)


async def test_admin_personal_reports_and_member_admin_mutations_are_rejected(setup):
    _, _, users, clients = setup
    admin = clients['admin']
    assert (await admin.get('/api/v1/reports')).status_code == 403
    assert (await admin.post('/api/v1/reports/generate',json={'kind':'daily','date':'2026-09-13'},headers=keyed())).status_code == 403
    assert (await admin.post('/api/v1/members',json={'username':'new_' + uuid4().hex,'name':'不能建管理员','role':'admin','password':'controlled-password'})).status_code == 403
    assert (await admin.post('/api/v1/members/' + users['admin'].id + '/reset-password',json={'password':'controlled-password'})).status_code == 404


async def test_member_creation_accepts_four_character_password_without_relaxing_access(setup):
    from test_dingtalk import app_for, browser
    _, _, _, clients = setup
    admin = clients['admin']
    payload = {'username': '111', 'name': '1', 'password': '1111'}
    invalid = await admin.post('/api/v1/members', json={'username': '1', 'name': '', 'password': '111'})
    assert invalid.status_code == 422
    detail = invalid.json()['error']
    assert detail['fields'] == ['body.username', 'body.name', 'body.password']
    assert detail['fieldErrors'] == {
        'username': '账号需为 3–80 位，仅支持字母、数字和 . _ @ -',
        'name': '姓名需为 1–80 个字符',
        'password': '密码需为 4–128 位',
    }
    assert (await admin.post('/api/v1/members', json=payload, headers={'X-CSRF-Token': 'wrong'})).status_code == 403
    for role in ('employee', 'outsider'):
        assert (await clients[role].post('/api/v1/members', json=payload)).status_code == 403
    assert (await admin.post('/api/v1/members', json={**payload, 'role': 'admin'})).status_code == 403

    created = await admin.post('/api/v1/members', json=payload)
    assert created.status_code == 201, created.text
    assert created.json()['role'] == 'employee'
    assert 'mustChangePassword' not in created.json()
    duplicate = await admin.post('/api/v1/members', json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()['error']['fieldErrors'] == {'username': '账号名称已被使用'}
    reset_path = '/api/v1/members/' + created.json()['id'] + '/reset-password'
    reset = await admin.post(reset_path, json={'password': '567'})
    assert reset.status_code == 422
    assert reset.json()['error']['fieldErrors'] == {'password': '密码需为 4–128 位'}
    async with browser(app_for(clients)) as client:
        login = await client.post('/api/v1/auth/login', json={key: payload[key] for key in ('username', 'password')})
        assert login.status_code == 200, login.text
        assert 'mustChangePassword' not in login.json()['member']
        client.headers['X-CSRF-Token'] = login.json()['csrf']
        assert (await client.get('/api/v1/work-items')).status_code == 200
        short = await client.post('/api/v1/auth/password', json={'currentPassword': '1111', 'newPassword': '567'})
        assert short.status_code == 422 and 'newPassword' in short.json()['error']['fieldErrors']
        wrong = await client.post('/api/v1/auth/password', json={'currentPassword': 'wrong', 'newPassword': '5678'})
        assert wrong.status_code == 400
        assert wrong.json()['error']['fieldErrors'] == {'currentPassword': '当前密码不正确'}
        assert (await client.post('/api/v1/auth/password', json={'currentPassword': '1111', 'newPassword': '5678'})).status_code == 200
        assert (await client.get('/api/v1/auth/me')).status_code == 401
        login = await client.post('/api/v1/auth/login', json={'username': payload['username'], 'password': '5678'})
        assert login.status_code == 200 and 'mustChangePassword' not in login.json()['member']
        assert (await client.get('/api/v1/work-items')).status_code == 200
        assert (await admin.post(reset_path, json={'password': '4321'})).status_code == 200
        assert (await client.get('/api/v1/auth/me')).status_code == 401
        login = await client.post('/api/v1/auth/login', json={'username': payload['username'], 'password': '4321'})
        assert login.status_code == 200 and 'mustChangePassword' not in login.json()['member']
        assert (await client.get('/api/v1/work-items')).status_code == 200
        assert (await client.post('/api/v1/auth/login', json={'username': payload['username'], 'password': '5678'})).status_code == 401


async def test_initial_admin_uses_same_password_requirement():
    from pydantic import ValidationError
    from app.modules.members.schemas import AdminBootstrap
    for password in ('123', 'x' * 129):
        with pytest.raises(ValidationError):
            AdminBootstrap(username='admin', name='管理员', password=password)
    assert AdminBootstrap(username='admin', name='管理员', password='1234').role == 'admin'


async def test_password_login_allows_business_and_feedback_without_change_step(setup):
    from test_dingtalk import app_for, browser
    _, sessions, users, clients = setup
    async with browser(app_for(clients)) as client:
        login = await client.post('/api/v1/auth/login', json={'username': users['employee'].username, 'password': 'controlled-test-password'})
        assert login.status_code == 200 and 'mustChangePassword' not in login.json()['member']
        client.headers['X-CSRF-Token'] = login.json()['csrf']
        assert 'mustChangePassword' not in (await client.get('/api/v1/auth/me')).json()['member']
        assert (await client.get('/api/v1/work-items')).status_code == 200
        conv = await conversation(client)
        sent = await message(client, conv)
        assert (await client.get('/api/v1/jobs/' + sent['jobId'] + '/feedback')).status_code == 200
        async with sessions.begin() as db:
            job = await db.get(Job, sent['jobId'])
            job.state = 'awaiting_input'
        stream = await client.get('/api/v1/jobs/' + sent['jobId'] + '/events')
        assert stream.status_code == 200 and 'event: snapshot' in stream.text and 'unavailable' not in stream.text
        assert (await client.get('/api/v1/members')).status_code == 403
