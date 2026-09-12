from datetime import timedelta
from dataclasses import replace
import io
import json
from uuid import uuid4

import pytest
from PIL import Image
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from paa_server.agent.harness import ALLOWED_TOOLS, RunContext, LostLease, lease, propose_progress
from paa_server.models import Company, Job, Member, Message, ProgressDraft, Report, ReportRevision, WorkItem, now
from paa_server.worker import claim, process_job, schedule_once
from paa_server.service import ensure_report
from fakes import controlled_model

pytestmark = pytest.mark.asyncio


def keyed():
    return {'Idempotency-Key': str(uuid4())}


async def send(client, text='初稿完成，等待报价', attachments=None):
    response = await client.post('/api/v1/messages', json={'text': text, 'attachmentIds': attachments or []}, headers=keyed())
    assert response.status_code == 202, response.text
    return response.json()


async def run_target(settings, sessions, users, result, scenario='progress'):
    # Claim only the test job, leaving user-created dev jobs untouched.
    async with sessions.begin() as db:
        job = await db.get(Job, result['jobId'])
        job.state, job.fence, job.lease_until = 'running', job.fence + 1, now() + timedelta(seconds=90)
    model = controlled_model(scenario)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=model)
    return model


async def test_real_harness_confirmation_followup_reports_and_visibility(setup):
    settings, sessions, users, clients = setup
    employee, admin, peer, outsider = (clients[k] for k in ('employee', 'admin', 'peer', 'outsider'))
    result = await send(employee)
    model = await run_target(settings, sessions, users, result)
    message = (await employee.get('/api/v1/messages/' + result['messageId'])).json()
    assert message['job']['state'] == 'succeeded', message
    assert set(model.seen_tools) == ALLOWED_TOOLS
    assert not (await employee.get('/api/v1/work-items')).json()['items']
    assert (await peer.get('/api/v1/messages/' + result['messageId'])).status_code == 404
    assert (await outsider.get('/api/v1/messages/' + result['messageId'])).status_code == 404
    draft = message['drafts'][0]
    edited = {**draft['content'], 'summary': '员工的私有更正', 'workId': None, 'expectedRevision': draft['revision']}
    saved = await employee.patch('/api/v1/progress-drafts/' + draft['id'], json=edited)
    assert saved.status_code == 200, saved.text
    public = (await admin.get('/api/v1/messages/' + result['messageId'])).json()
    assert public['drafts'] == []
    assert public['suggestions'][0]['content']['summary'] == '方案初稿已完成'
    assert '员工的私有更正' not in json.dumps(public, ensure_ascii=False)
    body = {'items': [{'id': draft['id'], 'expectedRevision': saved.json()['revision']}]}
    assert (await admin.post('/api/v1/progress-drafts/confirm', json=body, headers=keyed())).status_code == 404
    key = keyed()
    confirmed = await employee.post('/api/v1/progress-drafts/confirm', json=body, headers=key)
    assert confirmed.status_code == 200, confirmed.text
    assert (await employee.post('/api/v1/progress-drafts/confirm', json=body, headers=key)).json() == confirmed.json()
    work_id = confirmed.json()['workIds'][0]
    second = await send(employee, '报价拿到了')
    await run_target(settings, sessions, users, second)
    next_message = (await employee.get('/api/v1/messages/' + second['messageId'])).json()
    next_draft = next_message['drafts'][0]
    assert next_draft['workId'] == work_id
    work = (await employee.get('/api/v1/work-items/' + work_id)).json()
    changed = await employee.post(f'/api/v1/work-items/{work_id}/progress', json={**{k: work[k] for k in ('title','summary','status','blocker','nextStep')}, 'summary': '员工再次纠正，仍待核对', 'expectedRevision': work['revision'], 'sourceIds': [second['messageId']]})
    assert changed.status_code == 200, changed.text
    conflict = await employee.post('/api/v1/progress-drafts/confirm', json={'items': [{'id': next_draft['id'], 'expectedRevision': next_draft['revision']}]}, headers=keyed())
    assert conflict.status_code == 409
    day = now().date().isoformat()
    generated = await employee.post('/api/v1/reports/generate', json={'kind':'daily', 'date': day}, headers=keyed())
    assert generated.status_code == 202, generated.text
    report_id = generated.json()['reportId']
    await run_target(settings, sessions, users, generated.json(), 'report')
    report = (await employee.get('/api/v1/reports/' + report_id)).json()
    assert report['content']['completed'] == '已完成方案初稿', report
    assert (await admin.get('/api/v1/reports/' + report_id)).status_code == 404
    published = await employee.post(f'/api/v1/reports/{report_id}/submit', json={'expectedRevision':report['revision']}, headers=keyed())
    assert published.status_code == 200, published.text
    assert (await admin.get('/api/v1/reports/' + report_id)).json()['publishedRevision'] == report['revision']
    edited_report = await employee.patch('/api/v1/reports/' + report_id, json={'expectedRevision':report['revision'], 'content': {**report['content'], 'completed':'尚未提交的修改'}})
    assert edited_report.status_code == 200
    assert (await admin.get('/api/v1/reports/' + report_id)).json()['content']['completed'] == '已完成方案初稿'
    sources = (await admin.get(f'/api/v1/reports/{report_id}/sources')).json()
    assert sources['items'] and sources['items'][0]['workId'] == work_id
    regenerated = await employee.post('/api/v1/reports/generate', json={'kind':'daily', 'date':day}, headers=keyed())
    assert regenerated.json()['reportId'] == report_id
    assert regenerated.json()['jobId'] != generated.json()['jobId']
    await run_target(settings, sessions, users, regenerated.json(), 'report')
    report = (await employee.get('/api/v1/reports/' + report_id)).json()
    assert report['content']['completed'] == '尚未提交的修改'
    assert report['candidate']['content']['completed'] == '已完成方案初稿'


async def test_security_idempotency_disabled_account_and_request_validation(setup):
    settings, sessions, users, c = setup
    headers = keyed(); payload = {'text':'同一个操作'}
    first = await c['employee'].post('/api/v1/messages', json=payload, headers=headers)
    second = await c['employee'].post('/api/v1/messages', json=payload, headers=headers)
    assert first.json() == second.json()
    assert (await c['employee'].post('/api/v1/messages', json={'text':'不同内容'}, headers=headers)).status_code == 409
    assert (await c['employee'].post('/api/v1/messages', json={'text':'', 'ownerId':users['peer'].id}, headers=keyed())).status_code == 422
    assert (await c['employee'].post('/api/v1/messages', json=payload, headers={**keyed(), 'X-CSRF-Token':'invalid'})).status_code == 403
    assert (await c['employee'].post('/api/v1/messages', json=payload, headers={**keyed(), 'Origin':'https://other.invalid'})).status_code == 403
    assert (await c['employee'].get('/api/v1/members')).status_code == 403
    assert (await c['admin'].patch('/api/v1/members/' + users['admin'].id, json={'active':False})).status_code == 409
    assert (await c['admin'].patch('/api/v1/members/' + users['employee'].id, json={'active':False})).status_code == 200
    assert (await c['employee'].get('/api/v1/messages')).status_code == 401
    duplicate = await c['peer'].post('/api/v1/progress-drafts/confirm', json={'items':[{'id':'same','expectedRevision':1}]*2}, headers=keyed())
    assert duplicate.status_code == 422


async def test_images_remain_private_until_sent_and_enter_vision_harness(setup):
    settings, sessions, users, c = setup
    data = io.BytesIO(); Image.new('RGB', (120, 80), '#ffffff').save(data, format='PNG')
    upload = await c['employee'].post('/api/v1/uploads', files={'file':('sample.png',data.getvalue(),'image/png')})
    assert upload.status_code == 201, upload.text
    attachment = upload.json()
    assert (await c['admin'].get(attachment['url'])).status_code == 404
    result = await send(c['employee'], '这张图是今天的方案', [attachment['id']])
    assert (await c['admin'].get(attachment['url'])).status_code == 200
    assert (await c['peer'].get(attachment['url'])).status_code == 404
    model = await run_target(settings,sessions,users,result)
    assert model.seen_images[0]['image_url']['url'].startswith('data:image/jpeg;base64,')
    invalid = await c['employee'].post('/api/v1/uploads', files={'file':('fake.png',b'not an image','image/png')})
    assert invalid.status_code == 415


async def test_missing_provider_is_honest_and_expired_lease_requires_manual_retry(setup):
    settings, sessions, users, c = setup
    result = await send(c['employee'])
    async with sessions.begin() as db:
        job = await db.get(Job,result['jobId']); job.state='running'; job.fence=1; job.lease_until=now()+timedelta(seconds=90)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job,sessions,settings,saver)
    message = (await c['employee'].get('/api/v1/messages/'+result['messageId'])).json()
    assert message['job']['state']=='failed' and '暂未配置' in message['job']['error']
    assert not message['reply'] and not message['drafts']
    async with sessions.begin() as db:
        job = await db.get(Job,result['jobId']); job.state='running';job.lease_until=now()-timedelta(seconds=1);job.request_started=True
    # Explicitly recover only our row here; claim's recovery is separately exercised with a no-queued DB predicate.
    stale = RunContext(users['employee'].id,users['employee'].company_id,job.id,1,sessions,settings)
    async with sessions() as db:
        with pytest.raises(LostLease): await lease(db,stale)


async def test_report_schedule_rules_period_dedup_and_empty_regeneration(setup):
    settings,sessions,users,c=setup
    rules=(await c['admin'].get('/api/v1/settings/report-rules')).json()
    new={k:v for k,v in rules.items() if k!='revision'}
    new['expectedRevision']=rules['revision']; new['daily']={'enabled':True,'days':list(range(7)),'generateTime':'10:00','deadline':'18:00'}
    new['timezone']='Asia/Shanghai'
    assert (await c['employee'].put('/api/v1/settings/report-rules',json=new)).status_code==403
    assert (await c['admin'].put('/api/v1/settings/report-rules',json=new)).status_code==200
    assert (await c['admin'].put('/api/v1/settings/report-rules',json=new)).status_code==409
    async with sessions.begin() as db:
        company=await db.get(Company,users['employee'].company_id);company.rules_effective_at=now()-timedelta(days=2)
    from zoneinfo import ZoneInfo
    instant=now().astimezone(ZoneInfo('Asia/Shanghai')).replace(hour=11,minute=0)
    await schedule_once(sessions,instant);await schedule_once(sessions,instant)
    async with sessions() as db:
        reports=(await db.scalars(select(Report).where(Report.owner_id==users['employee'].id))).all()
        jobs=(await db.scalars(select(Job).where(Job.owner_id==users['employee'].id,Job.kind=='report'))).all()
        assert len(reports)==1 and len(jobs)==1
        assert jobs[0].phase=='empty'
    first=jobs[0].id
    response=await c['employee'].post('/api/v1/reports/generate',json={'kind':'daily','date':instant.date().isoformat()},headers=keyed())
    assert response.json()['jobId']!=first


async def test_team_excludes_admins_and_protects_other_admin_materials(setup):
    _, sessions, users, clients = setup
    async with sessions.begin() as db:
        peer = await db.get(Member, users['peer'].id)
        peer.role = 'admin'
        owner = users['admin']
        work = WorkItem(company_id=owner.company_id, owner_id=owner.id, title='管理员自己的事项', content={'title':'管理员自己的事项', 'summary':'不计入员工看板', 'status':'blocked', 'blocker':'等待', 'nextStep':''})
        report = Report(company_id=owner.company_id, owner_id=owner.id, kind='daily', period='2026-09-12', period_end='2026-09-12', timezone='Asia/Shanghai', content={'completed':'管理员自己的报告', 'ongoing':'', 'blockers':'', 'next':''}, published_revision=1)
        db.add_all([work, report]); await db.flush()
        db.add(ReportRevision(company_id=owner.company_id, owner_id=owner.id, report_id=report.id, revision=1, content=report.content, source_ids=[]))
    data = io.BytesIO(); Image.new('RGB', (2, 2), '#ffffff').save(data, format='PNG')
    uploaded = await clients['admin'].post('/api/v1/uploads', files={'file':('admin.png',data.getvalue(),'image/png')})
    assert uploaded.status_code == 201
    attachment = uploaded.json()
    sent = await send(clients['admin'], '管理员自己的上报', [attachment['id']])
    employee_message = await send(clients['employee'])
    for viewer in ('admin', 'peer'):
        client = clients[viewer]
        team = await client.get('/api/v1/team')
        assert team.status_code == 200
        assert [item['member']['id'] for item in team.json()['items']] == [users['employee'].id]
        assert sum(item['reportCount'] for item in team.json()['items']) == 0
        assert all(not item['work'] for item in team.json()['items'])
        for target in ('admin', 'peer'):
            for section in ('work', 'messages', 'reports'):
                assert (await client.get(f"/api/v1/team/members/{users[target].id}/{section}")).status_code == 404
        assert (await client.get(f"/api/v1/team/members/{users['employee'].id}/messages")).status_code == 200
        assert (await client.get('/api/v1/messages/' + employee_message['messageId'])).status_code == 200
        # Account administration remains available; it is separate from employee reporting.
        assert len((await client.get('/api/v1/members')).json()['items']) == 3
    for path in (f"/messages/{sent['messageId']}", f'/work-items/{work.id}', f'/reports/{report.id}', f'/reports/{report.id}/sources', attachment['url'].removeprefix('/api/v1')):
        assert (await clients['peer'].get('/api/v1' + path)).status_code == 404
        assert (await clients['admin'].get('/api/v1' + path)).status_code == 200
    assert (await clients['employee'].get('/api/v1/team')).status_code == 403
