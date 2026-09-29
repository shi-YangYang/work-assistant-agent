"""Fixed-response report commits, bounded dispatch and durable report schedules."""
import asyncio
import json
import pytest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from langchain_core.messages import AIMessage
from app.agent.runtime.model import reserve_call
from app.db.base import now
from app.modules.members.models import Company, Member
from app.modules.model_services.models import ModelUsage
from app.modules.reports.models import Report, ReportNotification, ReportObligation, ReportSchedule
from app.modules.reports.scheduling.schedule import eligibility_changed, save_schedule
from app.modules.reports.service import ensure_report
from app.modules.work.models import WorkItem, WorkRevision
from app.tasks.context import RunContext
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from app.tasks.runtime.runner import run_slots
from app.tasks.maintenance.scheduling import schedule_company
from sqlalchemy import func, select
from test_company import keyed
from uuid import uuid4



pytestmark = pytest.mark.asyncio
CONTENT = {'completed': '方案初稿已完成', 'ongoing': '等待确认', 'blockers': '', 'next': '继续核对'}


class ReportModel:
    def __init__(self, content=None, callback=None, finish='stop', verdict='{"valid":true}'):
        self.content = json.dumps(CONTENT, ensure_ascii=False) if content is None else content
        self.calls = 0
        self.callback = callback
        self.finish = finish
        self.inputs = []
        self.verdict, self.reviews = verdict, []

    async def ainvoke(self, messages):
        if json.loads(messages[-1].content).get('task') == 'report_fact_review':
            self.reviews.append(messages)
            return AIMessage(content=self.verdict)
        self.calls += 1
        self.inputs.append(messages)
        if self.callback:
            await self.callback()
        return AIMessage(content=self.content, response_metadata={'finish_reason': self.finish})


async def prepared(setup, *, day=None):
    settings, sessions, users, clients = setup
    actor = users['employee']
    instant = now()
    if day:
        instant = datetime.fromisoformat(day).replace(hour=6, tzinfo=timezone.utc)
    async with sessions.begin() as db:
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title='方案', content={'title': '方案', 'summary': '初稿完成', 'status': 'in_progress', 'blocker': '', 'nextStep': '等待确认'})
        db.add(work); await db.flush()
        revision = WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=1, content=work.content, source_ids=[], created_at=instant)
        db.add(revision); await db.flush()
        report, job = await ensure_report(db, actor, 'daily', instant.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date())
    return report, job, work


async def test_valid_report_without_tools_save_receipt_candidate_and_submit(setup):
    settings, sessions, users, c = setup
    report, job, work = await prepared(setup)
    response = ReportModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=response)
    async with sessions.begin() as db:
        saved = await db.get(Report, report.id)
        assert saved.content == CONTENT and saved.published_revision == 0
        live = await db.get(Job, job.id)
        assert live.result['reportSaved'] and live.state == 'succeeded'
        live.state, live.fence, live.lease_until = 'running', live.fence + 1, now() + timedelta(seconds=90)
    await process_job(live, sessions, settings, None, model=response)
    assert response.calls == 1
    assert (await c['admin'].get('/api/v1/reports/' + report.id)).status_code == 404
    second = await c['employee'].post('/api/v1/reports/generate', json={'kind':'daily','date':report.period}, headers=keyed())
    async def edit_and_submit():
        latest = (await c['employee'].get('/api/v1/reports/' + report.id)).json()
        edit = await c['employee'].patch('/api/v1/reports/' + report.id, json={'expectedRevision':latest['revision'],'content':{**CONTENT,'completed':'员工手动修改'}})
        assert edit.status_code == 200
        submit = await c['employee'].post(f'/api/v1/reports/{report.id}/submit',json={'expectedRevision':edit.json()['revision']},headers=keyed())
        assert submit.status_code == 200
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel(callback=edit_and_submit))
    result = (await c['employee'].get('/api/v1/reports/' + report.id)).json()
    assert result['content']['completed'] == '员工手动修改' and result['candidate']['content'] == CONTENT
    public = (await c['admin'].get('/api/v1/reports/' + report.id)).json()
    assert public['content']['completed'] == '员工手动修改' and public['candidate'] is None


@pytest.mark.parametrize(('content','finish'), [('普通聊天回复','stop'), ('{}','stop'), (json.dumps(dict.fromkeys(CONTENT,'')),'stop'), (json.dumps(CONTENT),'length')])
async def test_invalid_report_keeps_original_without_success(setup, content, finish):
    settings, sessions, users, _ = setup
    report, job, _ = await prepared(setup)
    async with sessions.begin() as db:
        saved = await db.get(Report, report.id); saved.content = {**CONTENT,'completed':'原内容'}
    model = ReportModel(content, finish=finish)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    async with sessions() as db:
        assert (await db.get(Report, report.id)).content['completed'] == '原内容'
        live = await db.get(Job,job.id)
        assert live.state == 'failed' and not live.result.get('reportSaved') and live.error
    assert model.calls == 1


@pytest.mark.parametrize('verdict', ['{"valid":false}', '{"valid":"true"}', '{}', 'invalid'])
async def test_report_fact_failure_keeps_original_and_never_regenerates_implicitly(setup, verdict):
    settings, sessions, users, _ = setup
    report, job, _ = await prepared(setup)
    async with sessions.begin() as db:
        saved = await db.get(Report, report.id); saved.content = {**CONTENT, 'completed': '原报告'}
    model = ReportModel(json.dumps({**CONTENT, 'completed': '整项方案已经完成'}), verdict=verdict)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        live = await db.get(Job, job.id)
        assert saved.content['completed'] == '原报告' and saved.candidate is None and not saved.published_revision
        assert live.state == 'failed' and not live.result.get('reportSaved')
    assert model.calls == 1 and len(model.reviews) == 1
    checked = json.loads(model.reviews[0][-1].content)
    assert checked['confirmed'][0]['content']['summary'] == '初稿完成'
    assert checked['report']['completed'] == '整项方案已经完成'


async def test_report_review_policy_change_rechecks_old_verdict_and_reuses_current_result(setup):
    from app.agent.reports import ReportVerdict, verify_report
    from app.core.digests import digest
    from app.tasks.nodes import node_execution
    from test_task_retry import enabled
    context, _ = await enabled(setup)
    payload = {'confirmed': [{'content': {'summary': '负责岗位招聘全流程，包括筛选、面试与入职安排', 'status': 'in_progress'}}]}
    content = {'completed': '', 'ongoing': '负责岗位招聘全流程，包括筛选、面试与入职安排', 'blockers': '', 'next': ''}
    async def legacy_review():
        return ReportVerdict(valid=False, reason='误把职责当成整体完成')
    await node_execution.execute_node(context, identity=digest({'payload': payload, 'content': content}),
        kind='review', label='核对报告内容中', operation=legacy_review,
        encode=lambda verdict: verdict.model_dump(), decode=ReportVerdict.model_validate,
        outcome=lambda verdict: ('awaiting_input', '内容与来源不一致'))
    model = ReportModel()
    await verify_report(context, payload, content, model)
    await verify_report(context, payload, content, model)
    assert model.calls == 0 and len(model.reviews) == 1
    assert json.loads(model.reviews[0][-1].content)['report'] == content
    async with context.sessions() as db:
        live = await db.get(Job, context.job_id)
        reviews = [row for row in live.result['nodeExecution']['nodes'] if row['kind'] == 'review']
        assert len(reviews) == 2
        assert reviews[0]['output']['valid'] is False and reviews[1]['output']['valid'] is True


async def test_rejected_draft_rechecks_new_policy_without_resetting_correction_budget(setup, monkeypatch):
    from app.agent import reports
    settings, sessions, users, clients = setup
    report, job, _ = await prepared(setup)
    async with sessions.begin() as db:
        live = await db.get(Job, job.id)
        live.result = {**live.result, 'instructions': '按已有工作整理报告，不提交'}
    rejected = ReportModel(verdict='{"valid":false,"reason":"来源阶段不符"}')
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=rejected)
    assert rejected.calls == 2 and len(rejected.reviews) == 2
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert live.result['reportDraft']['stage'] == 'rejected' and live.result['reportCorrectionAttempted']
        assert live.result['reportDraft']['reviewVersion'] == reports.REVIEW_VERSION
        assert not live.result.get('reportSaved')
        rejected_content = live.result['reportDraft']['content']
    unchanged = ReportModel()
    assert (await clients['employee'].post(f'/api/v1/jobs/{job.id}/retry', json={})).status_code == 200
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=unchanged)
    assert unchanged.calls == 0 and not unchanged.reviews
    monkeypatch.setattr(reports, 'REVIEW_VERSION', reports.REVIEW_VERSION + 1)
    current = ReportModel()
    assert (await clients['employee'].post(f'/api/v1/jobs/{job.id}/retry', json={})).status_code == 200
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=current)
    assert current.calls == 0 and len(current.reviews) == 1
    assert json.loads(current.reviews[0][-1].content)['report'] == rejected_content
    async with sessions() as db:
        live = await db.get(Job, job.id)
        saved = await db.get(Report, report.id)
        assert live.state == 'succeeded' and live.result['reportSaved'] and live.result['reportCorrectionAttempted']
        assert saved.content == rejected_content and not saved.published_revision


@pytest.mark.parametrize('change', ['delete_report', 'delete_work', 'inactive', 'role'])
async def test_report_late_response_cannot_restore_revoked_material(setup, change):
    settings, sessions, users, c = setup
    report, job, work = await prepared(setup)
    async def changed():
        async with sessions.begin() as db:
            if change == 'delete_report': (await db.get(Report, report.id)).deleted = True
            elif change == 'delete_work': (await db.get(WorkItem, work.id)).deleted = True
            elif change == 'inactive': (await db.get(Member, users['employee'].id)).active = False
            else: (await db.get(Member, users['employee'].id)).role = 'admin'
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel(callback=changed))
    async with sessions() as db:
        assert not (await db.get(Job,job.id)).result.get('reportSaved')
        assert not (await db.get(Report,report.id)).candidate


@asynccontextmanager
async def no_saver():
    yield None


async def test_thirty_members_parallel_bounded_fair_unique_and_one_owner(setup,monkeypatch):
    settings, sessions, users, _ = setup
    company = users['employee'].company_id
    from functools import partial
    monkeypatch.setattr('app.tasks.runtime.runner.claim',partial(claim,company_id=company))
    owners = []
    async with sessions.begin() as db:
        for index in range(30):
            member = Member(company_id=company, username='parallel_' + uuid4().hex, name='并行员工', password_hash='unused')
            db.add(member); await db.flush(); owners.append(member.id)
            db.add(Job(company_id=company, owner_id=member.id, kind='message', target_id=str(uuid4())))
        # The first owner has a second queued request; it cannot overlap itself.
        db.add(Job(company_id=company, owner_id=owners[0], kind='message', target_id=str(uuid4())))
    stop, slow, first_wave = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active, seen, maxima = set(), set(), []
    async def runner(job, sessions, settings, saver):
        assert job.owner_id not in active and job.id not in seen
        first = not seen
        active.add(job.owner_id); seen.add(job.id); maxima.append(len(active))
        if len(active) == 3: first_wave.set()
        await first_wave.wait()
        if job.owner_id == owners[0] and first:
            await slow.wait()
        else:
            await asyncio.sleep(0)
        async with sessions.begin() as db:
            live = await db.get(Job,job.id); live.state = 'failed' if job.owner_id == owners[1] else 'succeeded'; live.lease_until = None
        active.remove(job.owner_id)
        if len(seen) >= 30: slow.set()
        if len(seen) == 31 and not active: stop.set()
    await asyncio.wait_for(run_slots(sessions,replace(settings,worker_concurrency=3),stop,saver_factory=no_saver,runner=runner),20)
    assert len(seen) == 31 and max(maxima) == 3 and not active
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id.in_(owners),Job.state=='running')) == 0


async def test_slot_failure_is_supervised_and_shutdown_recovers_started_state(setup):
    settings,sessions,users,_=setup
    @asynccontextmanager
    async def unavailable():
        raise RuntimeError('controlled checkpoint unavailable')
        yield
    with pytest.raises(RuntimeError,match='checkpoint unavailable'):
        await asyncio.wait_for(run_slots(sessions,settings,asyncio.Event(),saver_factory=unavailable),2)
    from test_company import send
    await send(setup[3]['employee'])
    entered, stop = asyncio.Event(), asyncio.Event()
    async def blocked(job,sessions,settings,saver):
        context=RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,settings)
        usage_id=await reserve_call(context,'assistant')
        async with sessions.begin() as db:
            usage=await db.get(ModelUsage,usage_id);usage.status='running';usage.started_at=now()
        entered.set()
        await asyncio.Event().wait()
    running=asyncio.create_task(run_slots(sessions,replace(settings,worker_concurrency=1),stop,saver_factory=no_saver,runner=blocked,shutdown_timeout=0))
    await asyncio.wait_for(entered.wait(),3);stop.set();await running
    assert await claim(sessions,users['employee'].id) is None
    async with sessions() as db:
        live=await db.scalar(select(Job).where(Job.owner_id==users['employee'].id))
        usage=await db.scalar(select(ModelUsage).where(ModelUsage.job_id==live.id))
        assert live.state=='awaiting_retry' and usage.status=='unknown'


async def arrange(setup, instant, *, days_back=0):
    settings,sessions,users,_=setup
    async with sessions.begin() as db:
        company=await db.get(Company,users['employee'].company_id)
        company.rules={'timezone':'UTC','daily':{'enabled':True,'days':list(range(7)),'generateTime':'17:00','deadline':'18:00','reminders':True,'beforeMinutes':30},'weekly':{'enabled':False,'days':[4],'generateTime':'','deadline':''}}
        company.rules_effective_at=instant-timedelta(days=days_back+1)
        await save_schedule(db,company,company.rules_effective_at)
        for actor in [users['employee'],users['peer']]:
            await eligibility_changed(db,actor,instant-timedelta(days=days_back+2))


async def test_todos_no_work_reminders_read_submission_permissions_and_delete(setup,monkeypatch):
    settings,sessions,users,c=setup
    instant=datetime(2027,1,4,17,0,tzinfo=timezone.utc)
    await arrange(setup,instant)
    monkeypatch.setattr('app.modules.reports.scheduling.schedule.now',lambda:instant)
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    data=(await c['employee'].get('/api/v1/report-obligations')).json()
    assert len(data['items'])==1 and data['items'][0]['job']['phase']=='empty'
    obligation=data['items'][0]
    assert data['counts']['expected']==1 and data['counts']['submitted']==0
    assert (await c['admin'].get('/api/v1/report-obligations')).status_code==403
    assert (await c['peer'].post(f"/api/v1/report-obligations/{obligation['id']}/prepare",json={},headers=keyed())).status_code==404
    assert (await c['employee'].get('/api/v1/team/report-obligations')).status_code==403
    team=(await c['admin'].get('/api/v1/team/report-obligations?period=2027-01-04')).json()
    assert team['counts']['expected']==2 and all(row['reportId'] is None and 'job' not in row for row in team['items'])
    instant+=timedelta(minutes=30)
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    notices=(await c['employee'].get('/api/v1/notifications')).json()
    assert notices['unread']==1 and notices['items'][0]['stage']=='due'
    notice=notices['items'][0]
    assert (await c['peer'].post(f"/api/v1/notifications/{notice['id']}/read",json={})).status_code==404
    await c['employee'].post(f"/api/v1/notifications/{notice['id']}/read",json={})
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    assert (await c['employee'].get('/api/v1/notifications')).json()['unread']==0
    instant+=timedelta(hours=1)
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    notices=(await c['employee'].get('/api/v1/notifications')).json()
    assert len(notices['items'])==1 and notices['items'][0]['stage']=='overdue' and notices['unread']==1
    report=(await c['employee'].get('/api/v1/reports/'+obligation['reportId'])).json()
    edit=await c['employee'].patch('/api/v1/reports/'+report['id'],json={'expectedRevision':report['revision'],'content':{**dict.fromkeys(CONTENT,''),'ongoing':'本期无新增进展'}})
    assert edit.status_code==200
    assert (await c['employee'].post(f"/api/v1/reports/{report['id']}/submit",json={'expectedRevision':edit.json()['revision']},headers=keyed())).status_code==200
    assert (await c['employee'].get('/api/v1/notifications')).json()['items']==[]
    completed=(await c['employee'].get('/api/v1/report-obligations')).json()['items'][0]
    assert completed['state']=='submitted' and completed['submittedAt']
    # A correction remains submitted; deletion cancels the obligation permanently.
    edit2=await c['employee'].patch('/api/v1/reports/'+report['id'],json={'expectedRevision':edit.json()['revision'],'content':CONTENT})
    assert (await c['employee'].get('/api/v1/report-obligations')).json()['counts']['submitted']==1
    deletion=await c['admin'].request('DELETE','/api/v1/reports/'+report['id'],json={'expectedRevision':edit2.json()['revision']})
    assert deletion.status_code==200
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    cancelled=(await c['employee'].get('/api/v1/report-obligations')).json()['items'][0]
    assert cancelled['state']=='cancelled' and cancelled['reportId'] is None
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ModelUsage).where(ModelUsage.company_id==users['employee'].company_id))==0


async def test_bounded_outage_backfill_current_priority_future_rules_and_activation(setup):
    settings,sessions,users,c=setup
    instant=datetime(2027,2,8,17,15,tzinfo=timezone.utc)
    await arrange(setup,instant,days_back=120)
    await schedule_company(sessions,users['employee'].company_id,instant,4)
    async with sessions() as db:
        rows=(await db.scalars(select(ReportObligation).where(ReportObligation.company_id==users['employee'].company_id))).all()
        assert len(rows)<=8 and sum(row.period=='2027-02-08' for row in rows)==2
        jobs=(await db.scalars(select(Job).where(Job.company_id==users['employee'].company_id))).all()
        assert len(jobs)==2  # no historical model/job burst
        original=next(row for row in rows if row.owner_id==users['employee'].id and row.period=='2027-02-08')
    async with sessions.begin() as db:
        company=await db.get(Company,users['employee'].company_id)
        company.rules={**company.rules,'daily':{**company.rules['daily'],'deadline':'20:00'}};company.revision+=1
        await save_schedule(db,company,instant)
        member=await db.get(Member,users['peer'].id);member.active=False
        await eligibility_changed(db,member,instant)
    await schedule_company(sessions,users['employee'].company_id,instant+timedelta(days=1),4)
    async with sessions.begin() as db:
        unchanged=await db.get(ReportObligation,original.id)
        assert unchanged.deadline_at.hour==18
        nextday=await db.scalar(select(ReportObligation).where(ReportObligation.owner_id==users['employee'].id,ReportObligation.period=='2027-02-09'))
        assert nextday.deadline_at.hour==20
        member=await db.get(Member,users['peer'].id);member.active=True
        await eligibility_changed(db,member,instant+timedelta(days=2))
    await schedule_company(sessions,users['employee'].company_id,instant+timedelta(days=3),8)
    async with sessions() as db:
        periods=set((await db.scalars(select(ReportObligation.period).where(ReportObligation.owner_id==users['peer'].id,ReportObligation.state=='pending'))).all())
        assert '2027-02-11' in periods and not {'2027-02-09','2027-02-10'} & periods

async def test_unsent_reservation_requeues_but_old_fence_cannot_publish(setup):
    from app.tasks.lease import lease
    from app.tasks.context import LostLease
    from test_company import send
    settings,sessions,users,c=setup
    await send(c['employee'])
    old=await claim(sessions,users['employee'].id)
    context=RunContext(old.owner_id,old.company_id,old.id,old.fence,sessions,settings)
    usage_id=await reserve_call(context,'assistant')
    async with sessions.begin() as db:
        live=await db.get(Job,old.id);live.lease_until=now()-timedelta(seconds=1)
    fresh=await claim(sessions,users['employee'].id)
    assert fresh and fresh.fence>old.fence
    async with sessions() as db:
        assert (await db.get(ModelUsage,usage_id)).status=='not_sent'
        with pytest.raises(LostLease):await lease(db,context)


@pytest.mark.parametrize('reasoning_check', [False, True, 'explicit'])
async def test_structured_report_actual_request_usage_and_report_probe(setup,monkeypatch,reasoning_check):
    import httpx
    from test_model_services import create,payload,route
    settings,sessions,users,c=setup
    config=payload()
    if reasoning_check:
        config['baseUrl']='https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
        config['models'][0]['model']='deepseek-v4.1-flash'
    if reasoning_check == 'explicit':
        config['models'][0]['presets'] = [{'id': 'chosen', 'name': '显式推理', 'mode': 'advanced', 'parameters': {'enable_thinking': True, 'reasoning_effort': 'high'}}]
    saved=await create(c['admin'], config)
    routing=route(saved);routing['assistant']['streaming']=False
    if reasoning_check == 'explicit':
        routing['assistant']['presetId'] = 'chosen'
    await c['admin'].put('/api/v1/settings/model-routing',json=routing)
    report,job,_=await prepared(setup)
    requests=[]
    def respond(request):
        data=json.loads(request.content);requests.append(data)
        assert not data.get('tools') and not data.get('tool_choice')
        content='测试成功' if '只回复：测试成功' in str(data['messages']) else json.dumps(CONTENT,ensure_ascii=False)
        if reasoning_check and len(requests) <= 2:
            explicit_generation = reasoning_check == 'explicit' and len(requests) == 1
            assert data['enable_thinking'] is explicit_generation
            if explicit_generation:
                assert data['reasoning_effort'] == 'high'
            else:
                assert 'reasoning_effort' not in data
        if 'report_fact_review' in str(data['messages']):
            content='{"valid":true}'
            assert data['max_tokens'] == 2000
            if reasoning_check:
                assert data['enable_thinking'] is False and 'reasoning_effort' not in data
            else:
                assert 'enable_thinking' not in data
        return httpx.Response(200,json={'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':123,'completion_tokens':45,'total_tokens':168}})
    monkeypatch.setattr('app.integrations.models.transport.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    await process_job(await claim(sessions,users['employee'].id),sessions,settings,None)
    async with sessions() as db:
        assert (await db.get(Job,job.id)).state=='succeeded'
        usages=(await db.scalars(select(ModelUsage).where(ModelUsage.job_id==job.id))).all()
        assert len(usages)==2 and all(usage.status=='succeeded' and usage.kind=='report' and usage.actual_input_tokens==123 and usage.actual_output_tokens==45 for usage in usages)
    assert len(requests)==2
    result=await c['admin'].post('/api/v1/settings/model-services/test',json={**payload(),'models':[{**model,'streaming':False} for model in payload()['models']],'draftVersion':'report-json','modelId':'chat','purpose':'report'})
    assert result.status_code==200
    assert [check['state'] for check in result.json()['checks']]==['passed','passed'],result.text
    assert result.json()['checks'][-1]['name']=='报告结构' and len(requests)==4


async def test_ready_reminder_once_and_old_owner_execution_cancelled_on_disable(setup):
    from app.modules.reports.scheduling.schedule import draft_ready
    settings,sessions,users,c=setup
    instant=datetime(2027,3,1,17,tzinfo=timezone.utc)
    await arrange(setup,instant)
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    async with sessions.begin() as db:
        obligation=await db.scalar(select(ReportObligation).where(ReportObligation.owner_id==users['employee'].id))
        report=await db.get(Report,obligation.report_id)
        await draft_ready(db,report);await db.flush();await draft_ready(db,report)
    notices=(await c['employee'].get('/api/v1/notifications')).json()
    assert len(notices['items'])==1 and notices['items'][0]['stage']=='ready'
    from test_company import send
    await send(c['employee'])
    current=await claim(sessions,users['employee'].id)
    response=await c['admin'].patch('/api/v1/members/'+users['employee'].id,json={'active':False})
    assert response.status_code==200
    assert (await c['admin'].patch('/api/v1/members/'+users['employee'].id,json={'active':True})).status_code==200
    async with sessions() as db:
        live=await db.get(Job,current.id)
        assert live.state=='cancelled' and live.fence>current.fence
        assert (await db.get(ReportObligation,obligation.id)).state=='cancelled'
        assert await db.scalar(select(func.count()).select_from(ReportNotification).where(ReportNotification.owner_id==users['employee'].id))==0

async def test_newest_rule_revision_wins_even_if_timezone_moves_effective_date_back(setup):
    settings,sessions,users,c=setup
    instant=datetime(2027,4,4,17,tzinfo=timezone.utc)
    await arrange(setup,instant)
    async with sessions.begin() as db:
        company=await db.get(Company,users['employee'].company_id)
        old=await db.scalar(select(ReportSchedule).where(ReportSchedule.company_id==company.id,ReportSchedule.kind=='daily'))
        old.effective_period=old.next_period='2027-04-03'
        db.add(ReportSchedule(company_id=company.id,kind='daily',revision=2,timezone='UTC',rule={**company.rules['daily'],'deadline':'20:00'},effective_period='2027-04-02',next_period='2027-04-02'))
    await schedule_company(sessions,users['employee'].company_id,instant,50)
    async with sessions() as db:
        row=await db.scalar(select(ReportObligation).where(ReportObligation.owner_id==users['employee'].id,ReportObligation.period=='2027-04-04'))
        assert row.rule_revision==2 and row.deadline_at.hour==20


async def test_manual_report_retry_uses_latest_binding_without_overwriting_edits(setup):
    from app.modules.model_services.bindings import bind_job
    from test_model_services import create, route
    settings, sessions, users, c = setup
    service = await create(c['admin'])
    assert (await c['admin'].put('/api/v1/settings/model-routing', json=route(service))).status_code == 200
    report, job, _ = await prepared(setup)
    async with sessions.begin() as db:
        live = await db.get(Job, job.id)
        binding = await bind_job(db, live, settings)
        old_revision = binding['report']['revision']
        live.state = 'failed'
        saved = await db.get(Report, report.id)
        saved.content, saved.edited, saved.revision = {**CONTENT, 'completed': '人工编辑'}, True, 2
    from test_model_services import payload
    changed = payload()
    changed['expectedRevision'] = 1
    changed['name'] = '更新后的报告配置'
    response = await c['admin'].patch('/api/v1/settings/model-services/' + service['id'], json=changed)
    assert response.status_code == 200, response.text
    for use_current in (False,):
        result = await c['employee'].post('/api/v1/jobs/' + job.id + '/retry', json={'useCurrentConfig': use_current})
        assert result.status_code == 200, result.text
    assert (await c['employee'].post('/api/v1/jobs/' + job.id + '/retry', json={})).status_code == 409
    async with sessions.begin() as db:
        live = await db.get(Job, job.id)
        assert live.result['refreshModelBinding']
        binding = await bind_job(db, live, settings)
        assert binding['report']['revision'] > old_revision
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    async with sessions() as db:
        saved = await db.get(Report, report.id)
        assert saved.content['completed'] == '人工编辑' and saved.candidate['content'] == CONTENT


@pytest.mark.parametrize('host,model,expected', [
    ('https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'deepseek-v4.1-flash', {'enable_thinking': False}),
    ('https://api.deepseek.com', 'deepseek-chat', {'thinking': {'type': 'disabled'}}),
    ('https://unknown.example/v1', 'deepseek-v4.1-flash', {}),
])
async def test_report_default_mode_preserves_unknown_protocol_and_explicit_parameters(host, model, expected):
    from app.modules.model_services.parameters import report_model_config
    config = {'baseUrl': host, 'model': model, 'parameters': {'temperature': .2}}
    assert report_model_config(config, {})['parameters'] == {'temperature': .2, **expected}
    assert config['parameters'] == {'temperature': .2}
    assert report_model_config(config, {'presetId': 'selected'}) is config
    for parameters in ({'enable_thinking': True}, {'thinking': {'type': 'enabled'}}, {'reasoning_effort': 'high'}, {'thinking_budget': 3000}):
        explicit = {**config, 'parameters': parameters}
        assert report_model_config(explicit, {}) is explicit
