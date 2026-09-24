"""Real PostgreSQL queries and gated provider streams; no external model calls."""
import asyncio
import hashlib
import httpx
import json
import pytest
from datetime import date, datetime, timedelta, timezone
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.core.periods import period_range
from app.db.base import now
from app.modules.auth.models import Session
from app.modules.members.models import Company, Member
from app.modules.messages.models import Message
from app.modules.model_services.models import ModelUsage
from app.modules.model_services.usage import RequestRecord, usage_fields
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import WorkItem, WorkRevision
from app.security.access import scope as business_scope
from app.tasks.feedback import events, update_feedback
from app.tasks.handlers import process_job
from app.tasks.models import Job
from app.tasks.queue import claim
from sqlalchemy import delete
from test_company import send
from test_model_services import create, route




pytestmark = pytest.mark.asyncio


def content(title='工作', status='in_progress', blocker=''):
    return {'title':title,'summary':'方案摘要','status':status,'blocker':blocker,'nextStep':'下一步'}


async def work(db, actor, value, stamp, *, revision=1, access=None):
    item = WorkItem(company_id=actor.company_id,owner_id=actor.id,title=value['title'],content=value,updated_at=stamp,revision=revision,access=access or {})
    db.add(item); await db.flush()
    db.add(WorkRevision(company_id=actor.company_id,owner_id=actor.id,work_id=item.id,revision=revision,content=value,source_ids=[],created_at=stamp,access=access or {}))
    return item


async def test_full_authorized_search_stable_pages_and_deleted_anchor(setup):
    _, sessions, users, c = setup
    stamp = now()
    async with sessions.begin() as db:
        for index in range(125):
            await work(db,users['employee'],content('工作 '+str(index)),stamp)
        oldest = await work(db,users['employee'],content('历史 100%_方案', 'blocked','Escalate NEEDLE'),stamp-timedelta(days=50))
        for index in range(110):
            await work(db,users['employee'],content('禁止 '+str(index)),stamp+timedelta(days=1),access={'team':True,'actorId':users['admin'].id,'companyId':users['admin'].company_id,'role':'admin'})
        await work(db,users['peer'],content('其他人的 NEEDLE'),stamp)
    ids, cursor = [], None
    while True:
        result = await c['employee'].get('/api/v1/work-items',params={'cursor':cursor} if cursor else {})
        assert result.status_code == 200, result.text
        data = result.json()
        assert len(data['items']) <= 20
        ids += [row['id'] for row in data['items']]
        cursor = data['nextCursor']
        if not cursor: break
    assert len(ids) == len(set(ids)) == 126
    result = (await c['employee'].get('/api/v1/work-items',params={'q':'  nEeDLe  ','status':'blocked'})).json()
    assert [row['id'] for row in result['items']] == [oldest.id]
    assert len((await c['employee'].get('/api/v1/work-items',params={'q':'%_'})).json()['items']) == 1
    own = (await c['employee'].get('/api/v1/work-items')).json()
    team = (await c['admin'].get(f"/api/v1/team/members/{users['employee'].id}/work",params={'q':'NEEDLE'})).json()
    assert [row['id'] for row in team['items']] == [oldest.id]
    async with sessions.begin() as db:
        anchor = await db.get(WorkItem,own['items'][-1]['id']); anchor.deleted=True
    next_page = (await c['employee'].get('/api/v1/work-items',params={'cursor':own['nextCursor']})).json()
    assert next_page['items'] and not set(row['id'] for row in own['items']) & set(row['id'] for row in next_page['items'])
    assert (await c['outsider'].get(f"/api/v1/team/members/{users['employee'].id}/work")).status_code == 403


async def test_team_period_metrics_and_drilldowns_use_history_and_same_people(setup):
    _, sessions, users, c = setup
    stamp = datetime(2026,1,31,16,30,tzinfo=timezone.utc)  # Feb 1 in Shanghai
    async with sessions.begin() as db:
        company = await db.get(Company,users['admin'].company_id)
        company.rules = {**company.rules,'timezone':'Asia/Shanghai'}
        inactive = await db.get(Member,users['peer'].id); inactive.active=False
        for actor in (users['employee'],users['peer'],users['admin']):
            db.add(Message(company_id=actor.company_id,owner_id=actor.id,text='范围内上报',created_at=stamp))
        for index in range(105):
            item = await work(db,users['employee'],content('阻碍 '+str(index),'blocked','待材料'),stamp)
            if index == 0:
                historical_id = item.id
                item.content=content('后来已完成','done'); item.title='后来已完成'; item.revision=2;item.updated_at=stamp+timedelta(days=3)
                db.add(WorkRevision(company_id=item.company_id,owner_id=item.owner_id,work_id=item.id,revision=2,content=item.content,source_ids=[],created_at=item.updated_at))
        await work(db,users['employee'],content('完成但旧阻碍仍有文字','done','旧描述'),stamp)
        report=Report(company_id=users['employee'].company_id,owner_id=users['employee'].id,kind='daily',period='2026-02-01',period_end='2026-02-01',timezone='Asia/Shanghai',content={},revision=3,published_revision=3)
        db.add(report);await db.flush()
        for revision,days in ((1,0),(2,0),(3,3)):
            db.add(ReportRevision(company_id=report.company_id,owner_id=report.owner_id,report_id=report.id,revision=revision,content={'completed':str(revision)},source_ids=[],created_at=stamp+timedelta(days=days,minutes=revision)))
    filters={'period':'custom','start':'2026-02-01','end':'2026-02-01'}
    result=(await c['admin'].get('/api/v1/team',params=filters)).json()
    assert result['metrics']=={'reported':1,'members':1,'blocked':105,'reports':1}
    assert result['items'][0]['workCount']==106
    assert result['range']['timezone']=='Asia/Shanghai'
    for metric,total in [('messages',1),('blocked',105),('reports',1)]:
        seen=[];cursor=None
        while True:
            data=(await c['admin'].get('/api/v1/team/details',params={**filters,'metric':metric,**({'cursor':cursor} if cursor else {})})).json()
            assert data['total']==total and data['metrics']==result['metrics']
            seen.extend(data['items']);cursor=data['nextCursor']
            if not cursor:break
        assert len(seen)==total
        if metric=='reports':
            assert seen[0]['href'].endswith('revision=2')
    detail=(await c['admin'].get(f'/api/v1/work-items/{historical_id}?revision=1')).json()
    assert detail['status']=='blocked' and detail['historical']
    report_detail=(await c['admin'].get(f'/api/v1/reports/{report.id}?revision=2')).json()
    assert report_detail['content']['completed']=='2'
    done=(await c['admin'].get('/api/v1/team',params={**filters,'status':'done'})).json()
    assert done['metrics']=={'reported':1,'members':1,'blocked':0,'reports':1}
    assert done['items'][0]['workCount']==1
    inactive=(await c['admin'].get('/api/v1/team',params={**filters,'members':'inactive'})).json()
    assert inactive['metrics']=={'reported':1,'members':1,'blocked':0,'reports':0}
    empty=(await c['admin'].get('/api/v1/team',params={**filters,'q':'不存在员工'})).json()
    assert empty['metrics']=={'reported':0,'members':0,'blocked':0,'reports':0}
    assert (await c['admin'].get('/api/v1/team',params={'period':'custom','start':'2026-02-02','end':'2026-02-01'})).status_code==422
    assert (await c['employee'].get('/api/v1/team/details',params={**filters,'metric':'reports'})).status_code==403


async def test_company_period_dst_calendar_boundaries():
    company=Company(rules={'timezone':'America/New_York'})
    lower,upper,_=period_range(company,'custom',date(2026,3,8),date(2026,3,8))
    assert (upper.astimezone(timezone.utc)-lower.astimezone(timezone.utc)).total_seconds()==23*3600
    lower,upper,scope=period_range(company,'this_week',instant=datetime(2026,1,1,tzinfo=timezone.utc))
    assert scope['start']=='2025-12-29' and scope['end']=='2026-01-04'


class GatedStream(httpx.AsyncByteStream):
    def __init__(self, seen, release, *, interrupted=False, tools=False):
        self.seen,self.release,self.interrupted,self.tools=seen,release,interrupted,tools
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        self.seen.set()
        await self.release.wait()
        if self.tools:
            part={'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call_1','function':{'name':'find_work_items','arguments':'{"query":"secret argument"}'}}]},'finish_reason':'tool_calls'}]}
        else:
            part={'choices':[{'delta':{'content':'world'},'finish_reason':'stop'}]}
        yield ('data: '+json.dumps(part)+'\n\n').encode()
        yield b'data: {"choices":[],"usage":{"prompt_tokens":0,"completion_tokens":7}}\n\n'
        if not self.interrupted:
            yield b'data: [DONE]\n\n'


@pytest.mark.parametrize('role,interrupted,tools', [('employee',False,False),('admin',False,False),('employee',True,False),('employee',False,True)])
async def test_stage_feedback_precedes_reviewed_reply_and_preserves_usage(setup,monkeypatch,role,interrupted,tools):
    settings,sessions,users,c=setup
    saved=await create(c['admin'])
    assert (await c['admin'].put('/api/v1/settings/model-routing',json=route(saved))).status_code==200
    sent=await send(c[role],'只需正常回复，无需新增工作。')
    job=await claim(sessions,users[role].id)
    seen,release=asyncio.Event(),asyncio.Event()
    calls=[]
    def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        if not payload.get('tools'):
            # Independent presentation request is counted like every provider call.
            verdict = json.dumps({'segments': [{'index': 0, 'kind': 'information', 'evidence': []}]})
            event = {'choices': [{'delta': {'content': verdict}, 'finish_reason': 'stop'}]}
            wire = 'data: ' + json.dumps(event) + '\n\ndata: {"choices":[],"usage":{"prompt_tokens":0,"completion_tokens":7}}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=wire, headers={'content-type': 'text/event-stream'})
        return httpx.Response(200,stream=GatedStream(seen,release,interrupted=interrupted,tools=tools and len(calls)==1))
    monkeypatch.setattr('app.integrations.models.transport.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        task=asyncio.create_task(process_job(job,sessions,settings,saver))
        try:
            await asyncio.wait_for(seen.wait(),15)
            live=await c[role].get(f"/api/v1/jobs/{job.id}/feedback")
            assert live.status_code==200,live.text
            assert live.json()['text']=='' and live.json()['stage']=='generating' and not task.done()
            restored=await c[role].get(f"/api/v1/jobs/{job.id}/feedback")
            assert restored.json()==live.json() and len(calls)==1
            assert (await c['peer'].get(f"/api/v1/jobs/{job.id}/feedback")).status_code==404
            assert (await c['outsider'].get(f"/api/v1/jobs/{job.id}/feedback")).status_code==404
            token=hashlib.sha256(c[role].cookies.get('paa_company_session').encode()).hexdigest()
            stream=events(sessions,token,job.id)
            assert '"stage": "generating"' in await anext(stream)
            await stream.aclose()  # Disconnect is read-only, worker remains running.
            assert not task.done()
            # Capture actual ASGI HTTP delivery: ASGITransport normally buffers
            # StreamingResponse, so it cannot prove first-byte delivery.
            delivered=asyncio.Event()
            bodies=[]
            async def receive():
                await asyncio.Event().wait()
            async def capture(event):
                if event['type']=='http.response.body':
                    bodies.append(event.get('body',b''))
                    if b'"stage": "generating"' in event.get('body',b''):
                        delivered.set()
            scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1','method':'GET','scheme':'http','path':f'/api/v1/jobs/{job.id}/events','raw_path':f'/api/v1/jobs/{job.id}/events'.encode(),'query_string':b'','root_path':'','headers':[(b'host',b'test'),(b'cookie',f"paa_company_session={c[role].cookies.get('paa_company_session')}".encode())],'client':('127.0.0.1',1),'server':('test',80)}
            subscription=asyncio.create_task(c[role]._transport.app(scope,receive,capture))
            try:
                await asyncio.wait_for(delivered.wait(),5)
                assert not task.done() and b'secret argument' not in b''.join(bodies) and b'Hello' not in b''.join(bodies)
            finally:
                subscription.cancel()
                await asyncio.gather(subscription,return_exceptions=True)
        finally:
            release.set()
            await asyncio.wait_for(task,15)
    data=(await c[role].get('/api/v1/messages/'+sent['messageId'])).json()
    if interrupted:
        assert data['job']['state']=='awaiting_retry' and not data['reply']
        assert (await c[role].get(f"/api/v1/jobs/{job.id}/feedback")).json()['text']==''
    else:
        assert data['job']['state']=='awaiting_input' and data['reply']=='Hello world'
        assert (await c[role].get(f"/api/v1/jobs/{job.id}/feedback")).json()['text']==''
    usage=(await c['admin'].get('/api/v1/settings/model-usage')).json()
    expected_calls=4 if interrupted else (2 if tools else 1) + 1
    if interrupted:
        assert data['job']['nodes'][0]['attempts']==4 and data['job']['nodes'][0]['retries']==3
    assert usage['summary']['calls']==expected_calls and usage['summary']['inputTokens']==0 and usage['summary']['inputKnown']==expected_calls
    row=usage['items'][0]
    assert row['inputTokens']==0 and row['outputTokens']==7 and row['model']=='controlled-chat'
    assert row['state']==('unknown' if interrupted else 'succeeded')
    assert len(calls)==expected_calls
    wire=await c[role].get(f'/api/v1/jobs/{job.id}/events')
    assert wire.status_code==200 and 'no-transform' in wire.headers['cache-control']
    assert 'secret argument' not in wire.text


async def test_feedback_live_authorization_and_stale_writer(setup):
    settings,sessions,users,c=setup
    from app.tasks.context import RunContext, LostLease
    from app.tasks.feedback import publish
    sent=await send(c['admin'],'查询')
    job=await claim(sessions,users['admin'].id)
    context=RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,settings)
    await publish(context,'generating','本人普通答复',force=True)
    async with sessions.begin() as db:
        live=await db.get(Job,job.id)
        live.access={**business_scope(users['admin']),'team':True,'reads':{}}
    await publish(context,'generating','团队未校验内容',force=True)
    assert (await c['admin'].get(f'/api/v1/jobs/{job.id}/feedback')).json()['text']==''
    async with sessions.begin() as db:
        live=await db.get(Job,job.id);live.fence+=1
    with pytest.raises(LostLease):
        await publish(context,'generating','旧尝试迟到正文',force=True)
    token=hashlib.sha256(c['admin'].cookies.get('paa_company_session').encode()).hexdigest()
    async with sessions.begin() as db:
        await db.execute(delete(Session).where(Session.token_hash==token))
    stream=events(sessions,token,job.id)
    assert 'unavailable' in await anext(stream)
    await stream.aclose()
    assert (await c['admin'].get(f'/api/v1/jobs/{job.id}/feedback')).status_code==401


async def test_usage_actual_unknown_failure_legacy_and_snapshots(setup):
    _,sessions,users,c=setup
    actor=users['admin']
    async with sessions.begin() as db:
        legacy=ModelUsage(company_id=actor.company_id,owner_id=actor.id,kind='assistant',input_tokens=99000,output_tokens=88000)
        db.add(legacy)
        records=[]
        for _ in range(4):
            row=ModelUsage(company_id=actor.company_id,owner_id=actor.id,kind='assistant',**usage_fields({'name':'旧服务名','model':'旧模型'}))
            db.add(row);await db.flush();records.append(row.id)
    success=RequestRecord(sessions,records[0]);await success.event('started');await success.event('usage',{'prompt_tokens':0});await success.finish()
    failed=RequestRecord(sessions,records[1]);await failed.event('started')
    from app.integrations.models.transport import ProviderError
    await failed.finish(ProviderError('authentication','鉴权失败',401))
    uncertain=RequestRecord(sessions,records[2]);await uncertain.event('started');await uncertain.finish(asyncio.TimeoutError())
    result=(await c['admin'].get('/api/v1/settings/model-usage')).json()
    assert result['summary']['calls']==3 and result['summary']['successRate']==0.5
    assert result['summary']['inputTokens']==0 and result['summary']['inputKnown']==1 and result['summary']['outputKnown']==0
    assert result['summary']['states']['legacy']==1 and result['summary']['states']['reserved']==1
    assert all(row['model']=='旧模型' for row in result['items'] if row['state']!='legacy')
    for role in ('employee','peer','outsider'):
        assert (await c[role].get('/api/v1/settings/model-usage')).status_code==403
    async with sessions.begin() as db:
        outsider=await db.get(Member,users['outsider'].id);outsider.role='admin'
    assert (await c['outsider'].get('/api/v1/settings/model-usage')).json()['items']==[]


@pytest.mark.parametrize('protocol', ['chat', 'transcriptions'])
async def test_usage_address_rejection_not_sent_but_http_redirect_is_failed(setup, monkeypatch, protocol):
    from dataclasses import replace
    from httpcore._backends.auto import AutoBackend
    from app.integrations.models.transport import ProviderError
    from app.integrations.models.chat import chat
    from app.integrations.models.asr import transcribe

    settings, sessions, users, c = setup
    settings = replace(settings, model_allowed_origins=())
    actor = users['admin']
    config = {'baseUrl':'https://127.0.0.1/v1', 'model':'controlled', 'protocol':protocol, 'streaming':False}

    async def unexpected_connect(*args, **kwargs):
        pytest.fail('Restricted DNS result must be rejected before connecting')

    monkeypatch.setattr(AutoBackend, 'connect_tcp', unexpected_connect)

    async def invoke():
        async with sessions.begin() as db:
            row = ModelUsage(company_id=actor.company_id, owner_id=actor.id, kind='test', **usage_fields(config))
            db.add(row)
            await db.flush()
        record = RequestRecord(sessions, row.id)
        if protocol == 'chat':
            return await record.run(lambda event: chat(settings, config, 'controlled-key', [{'role':'user','content':'test'}], on_event=event))
        return await record.run(lambda event: transcribe(settings, config, 'controlled-key', b'RIFF', on_event=event))

    # Use the real SafeTransport and DNS address guard, not a fabricated error.
    with pytest.raises(ProviderError, match='受限制网络') as rejected:
        await invoke()
    assert rejected.value.code == 'address' and rejected.value.status is None
    result = (await c['admin'].get('/api/v1/settings/model-usage')).json()
    assert result['summary']['calls'] == 0 and result['summary']['successRate'] is None
    assert result['summary']['averageMs'] is None and result['summary']['durationKnown'] == 0
    assert result['summary']['states']['not_sent'] == 1
    assert result['items'][0]['startedAt'] is None and result['items'][0]['elapsedMs'] is None
    assert result['items'][0]['errorCode'] == 'address'

    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(307, headers={'Location':'https://example.com/v1'})

    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(redirect)))
    with pytest.raises(ProviderError, match='重定向') as remote:
        await invoke()
    assert remote.value.code == 'address' and remote.value.status == 307 and len(requests) == 1
    result = (await c['admin'].get('/api/v1/settings/model-usage')).json()
    assert result['summary']['calls'] == 1 and result['summary']['successRate'] == 0
    assert result['summary']['durationKnown'] == 1
    assert result['summary']['states']['not_sent'] == result['summary']['states']['failed'] == 1
    failed = next(row for row in result['items'] if row['state'] == 'failed')
    assert failed['startedAt'] is not None and failed['elapsedMs'] >= 0


async def test_document_stage_follows_actual_parse_and_feedback_expires(setup):
    from app.tasks.context import RunContext
    from app.tasks.documents import prepare_document
    settings,sessions,users,c=setup
    uploaded=await c['employee'].post('/api/v1/uploads',files={'file':('note.txt',b'Plain document','text/plain')})
    assert uploaded.status_code==201,uploaded.text
    result=await c['employee'].post('/api/v1/messages',json={'text':'查看资料','attachmentIds':[uploaded.json()['id']]},headers={'Idempotency-Key':'document-stage'})
    assert result.status_code==202,result.text
    job=await claim(sessions,users['employee'].id)
    context=RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,settings)
    await prepare_document(context,uploaded.json()['id'])
    assert (await c['employee'].get(f'/api/v1/jobs/{job.id}/feedback')).json()['stage']=='parsing'
    async with sessions.begin() as db:
        live=await db.get(Job,job.id);update_feedback(live,'generating','临时正文')
    await prepare_document(context,uploaded.json()['id'])
    assert (await c['employee'].get(f'/api/v1/jobs/{job.id}/feedback')).json()['stage']=='generating'
    async with sessions.begin() as db:
        live=await db.get(Job,job.id);live.state='awaiting_retry';live.updated_at=now()-timedelta(days=2)
    assert (await c['employee'].get(f'/api/v1/jobs/{job.id}/feedback')).json()['text']==''
