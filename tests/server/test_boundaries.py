import asyncio
from dataclasses import replace
from datetime import timedelta
import io
import json
import wave
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from paa_server.agent.harness import BudgetExceeded, RunContext, LostLease, lease, reserve_call
from paa_server.models import Attachment, Job, Message, WorkItem, now
from paa_server.worker import asr, claim, process_job
from fakes import controlled_model
from test_company import send

pytestmark=pytest.mark.asyncio


async def test_queue_serializes_owner_fences_old_worker_and_stops_uncertain_retry(setup):
    settings,sessions,users,c=setup
    a=await send(c['employee'],'第一条'); b=await send(c['employee'],'第二条')
    claimed=await claim(sessions, users['employee'].id)
    assert claimed.id==a['jobId'] and claimed.state=='running'
    assert await claim(sessions,users['employee'].id) is None
    async with sessions.begin() as db:
        old=await db.get(Job,claimed.id);old.request_started=True;old.lease_until=now()-timedelta(seconds=1)
    next_job=await claim(sessions,users['employee'].id)
    assert next_job.id==b['jobId']
    async with sessions() as db:
        old=await db.get(Job,claimed.id);assert old.state=='awaiting_retry'
        with pytest.raises(LostLease):
            await lease(db,RunContext(users['employee'].id,users['employee'].company_id,old.id,claimed.fence,sessions,settings))
    retry=await c['employee'].post('/api/v1/jobs/'+old.id+'/retry',json={})
    assert retry.status_code==200 and retry.json()['state']=='queued'


async def test_voice_is_decoded_original_retained_and_corrected_asr_is_versioned(setup,monkeypatch):
    settings,sessions,users,c=setup
    audio=io.BytesIO()
    with wave.open(audio,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000);writer.writeframes(b'\0\0'*16000)
    uploaded=await c['employee'].post('/api/v1/uploads',files={'file':('controlled.wav',audio.getvalue(),'audio/wav')})
    assert uploaded.status_code==201,uploaded.text
    attachment=uploaded.json();assert attachment['duration']==1
    result=await send(c['employee'],'语音样本',[attachment['id']])
    requested=[]
    def response(request):
        body=json.loads(request.content);requested.append(body)
        assert body['messages'][0]['content'][0]['input_audio']['data'].startswith('data:audio/wav;base64,')
        return httpx.Response(200,json={'choices':[{'message':{'content':'方案完成，等待报价'}}]})
    original_client=httpx.AsyncClient
    def mock_client(settings): return original_client(transport=httpx.MockTransport(response))
    monkeypatch.setattr('paa_server.model_provider.client', mock_client)
    configured=replace(settings,asr_base_url='https://controlled.invalid/v1',asr_key='test-only-key')
    async with sessions.begin() as db:
        job=await db.get(Job,result['jobId']);job.state='running';job.fence=1;job.lease_until=now()+timedelta(seconds=90)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job,sessions,configured,saver,model=controlled_model())
    message=(await c['employee'].get('/api/v1/messages/'+result['messageId'])).json()
    assert message['transcript']=='方案完成，等待报价',message
    assert len(requested)==1
    revised=await c['employee'].patch('/api/v1/messages/'+message['id']+'/transcript',json={'text':'仅初稿完成','expectedRevision':1})
    assert revised.status_code==200 and revised.json()['transcriptRevision']==2
    assert (await c['employee'].patch('/api/v1/messages/'+message['id']+'/transcript',json={'text':'旧页面','expectedRevision':1})).status_code==409
    assert (settings.media_dir/attachment['id']).read_bytes()==audio.getvalue()
    assert (await c['peer'].get(attachment['url'])).status_code==404


async def test_daily_and_per_run_model_limits_before_external_calls(setup):
    settings,sessions,users,c=setup
    result=await send(c['employee'])
    job=await claim(sessions,users['employee'].id)
    context=RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,replace(settings,daily_calls=1))
    await reserve_call(context,'agent',100)
    with pytest.raises(BudgetExceeded): await reserve_call(context,'agent',100)
    context.calls=8
    with pytest.raises(BudgetExceeded): await reserve_call(context,'agent')


async def test_concurrent_idempotent_send_returns_one_message(setup):
    settings,sessions,users,c=setup
    key={'Idempotency-Key':str(uuid4())}
    responses=await asyncio.gather(*[c['employee'].post('/api/v1/messages',json={'text':'并发发送同一内容'},headers=key) for _ in range(2)])
    assert all(r.status_code==202 for r in responses),[r.text for r in responses]
    assert responses[0].json()==responses[1].json()

async def test_long_conversation_is_summarized_before_hard_context_limit(setup):
    from paa_server.agent.harness import invoke_harness
    settings,sessions,users,c=setup
    actor=users['employee']
    async with sessions.begin() as db:
        for index in range(10):
            db.add(Message(company_id=actor.company_id,owner_id=actor.id,text='历史方案讨论。'*180,reply='此前的讨论记录。'*100,created_at=now()-timedelta(minutes=index+1)))
    await send(c['employee'],'今天继续方案。'*700)
    job=await claim(sessions,actor.id)
    context=RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,settings,source_revision=0)
    model=controlled_model()
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        answer=await invoke_harness(context,saver,'今天继续方案。'*700,model)
        assert answer and model.summaries
        await saver.adelete_thread(f'{job.company_id}:{job.owner_id}:job:{job.id}')


async def test_tool_cannot_bless_a_work_revision_it_did_not_read(setup):
    from types import SimpleNamespace
    from paa_server.agent.harness import propose_progress
    settings,sessions,users,c=setup
    result=await send(c['employee'])
    job=await claim(sessions,users['employee'].id)
    context=RunContext(job.owner_id,job.company_id,job.id,job.fence,sessions,settings)
    async with sessions.begin() as db:
        work=WorkItem(company_id=job.company_id,owner_id=job.owner_id,title='已纠正的工作',content={'title':'已纠正的工作','summary':'最新人工内容','status':'in_progress','blocker':'','nextStep':''})
        db.add(work);await db.flush();work_id=work.id
    runtime=SimpleNamespace(context=context)
    answer=await propose_progress.coroutine(title='旧推断',summary='模型旧内容',status='in_progress',blocker='',next_step='',work_id=work_id,runtime=runtime)
    assert '重新读取' in answer
    async with sessions() as db:
        assert (await db.get(WorkItem,work_id)).content['summary']=='最新人工内容'


@pytest.mark.parametrize('fail_commit', [False, True])
async def test_progress_confirmation_commits_before_success_response(setup, monkeypatch, fail_commit):
    from uuid import uuid4
    import httpx
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession
    from paa_server.models import ProgressDraft, WorkRevision
    settings, sessions, users, clients = setup
    actor = users['employee']
    old = {'title':'提交顺序', 'summary':'旧进展', 'status':'blocked', 'blocker':'等待报价', 'nextStep':'测算'}
    async with sessions.begin() as db:
        message = Message(company_id=actor.company_id, owner_id=actor.id, text='报价已到')
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=old['title'], content=old)
        db.add_all([message, work])
        await db.flush()
        draft = ProgressDraft(company_id=actor.company_id, owner_id=actor.id, message_id=message.id, work_id=work.id, base_revision=1, content={**old,'summary':'报价已到','status':'in_progress','blocker':''}, tool_key=uuid4().hex)
        db.add(draft)
        await db.flush()
    original_commit = AsyncSession.commit
    async def commit(db):
        if fail_commit and any(isinstance(item, WorkItem) and item.id == work.id for item in db.dirty):
            raise SQLAlchemyError('controlled commit failure')
        await original_commit(db)
    monkeypatch.setattr(AsyncSession, 'commit', commit)
    observed = []
    app = clients['employee']._transport.app
    async def observed_app(scope, receive, send):
        async def capture(event):
            if event['type'] == 'http.response.start':
                async with sessions() as db:
                    current = await db.get(WorkItem, work.id)
                    history = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id))
                    observed.append((event['status'], current.revision, current.content['summary'], history is not None))
            await send(event)
        await app(scope, receive, capture)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=observed_app), base_url='http://test', headers=clients['employee'].headers, cookies=clients['employee'].cookies) as client:
        result = await client.post('/api/v1/progress-drafts/confirm', json={'items':[{'id':draft.id,'expectedRevision':1}]}, headers={'Idempotency-Key':uuid4().hex})
    if fail_commit:
        assert result.status_code == 503
        assert observed == [(503, 1, '旧进展', False)]
    else:
        assert result.status_code == 200
        assert observed == [(200, 2, '报价已到', True)]
