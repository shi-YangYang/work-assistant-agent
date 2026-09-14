"""Company model boundary regressions against PostgreSQL and controlled HTTP responses."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from paa_server.models import Company, Job, ModelRouting, ModelService, ModelServiceRevision, ModelUsage
from paa_server.model_secrets import SecretUnavailable, decrypt, encrypt, initialize_key
from paa_server.model_provider import CheckedBackend, ProviderError, SafeTransport, allowed_address, chat, normalize_url, request_options, transcribe
from paa_server.model_services import bind_job, resolve_bound
from paa_server.model_schemas import ServiceInput, parameters
from paa_server.worker import claim, process_job
from test_company import send
from test_recovery import model

pytestmark = pytest.mark.asyncio
SECRET='controlled-key-not-real'


def payload(name='服务甲', url='https://example.com/v1'):
    return {'name': name, 'baseUrl': url, 'apiKey': SECRET, 'models': [{'id': 'chat', 'model': 'controlled-chat', 'protocol': 'chat'}, {'id': 'audio', 'model': 'controlled-asr', 'protocol': 'transcriptions'}], 'expectedRevision': 0}


async def create(c, body=None):
    response = await c.post('/api/v1/settings/model-services', json=body or payload())
    assert response.status_code == 201, response.text
    return response.json()


def route(saved, revision=0):
    choice = {'serviceId': saved['id'], 'modelId': 'chat', 'presetId': None, 'streaming': True}
    return {'expectedRevision': revision, 'assistant': choice, 'report': 'follow', 'asr': {**choice, 'modelId':'audio', 'streaming':False}}


async def test_model_service_auth_encryption_version_address_and_delete(setup):
    settings, sessions, users, c = setup
    for role in ('employee', 'peer', 'outsider'):
        assert (await c[role].get('/api/v1/settings/model-services')).status_code == 403
        assert (await c[role].post('/api/v1/settings/model-services/models', json={**payload(), 'draftVersion':'v1'})).status_code == 403
    saved = await create(c['admin'])
    assert SECRET not in json.dumps(saved) and saved['hasKey']
    assert saved['models'][0]['streaming'] is True
    async with sessions() as db:
        revision = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id == saved['id']))
        assert SECRET not in revision.credential
        assert decrypt(settings.model_key_file, revision.credential, users['admin'].company_id, saved['id'], 1) == SECRET
        with pytest.raises(SecretUnavailable):
            decrypt(settings.model_key_file, revision.credential, users['outsider'].company_id, saved['id'], 1)
    body = {**payload(), 'apiKey':'', 'expectedRevision':1}
    changed = await c['admin'].patch('/api/v1/settings/model-services/'+saved['id'], json={**body,'baseUrl':'https://other.example/v1'})
    assert changed.status_code == 422
    response = await c['admin'].patch('/api/v1/settings/model-services/'+saved['id'], json=body)
    assert response.status_code == 200 and response.json()['revision']==2
    assert (await c['admin'].patch('/api/v1/settings/model-services/'+saved['id'], json=body)).status_code == 409
    assigned = await c['admin'].put('/api/v1/settings/model-routing', json=route(saved))
    assert assigned.status_code == 200
    assert (await c['admin'].request('DELETE', '/api/v1/settings/model-services/'+saved['id'], json={'expectedRevision':2})).status_code == 409
    assert (await c['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision':1,'assistant':None,'report':None,'asr':None})).status_code == 200
    assert (await c['admin'].request('DELETE','/api/v1/settings/model-services/'+saved['id'], json={'expectedRevision':2})).status_code == 200
    async with sessions() as db:
        rows=(await db.scalars(select(ModelServiceRevision).where(ModelServiceRevision.service_id==saved['id']))).all()
        assert all(r.credential=='' for r in rows)


async def test_cross_company_csrf_secret_failure_and_environment_takeover(setup):
    settings, sessions, users, c = setup
    saved = await create(c['admin'])
    async with sessions.begin() as db:
        outsider=await db.get(__import__('paa_server.models',fromlist=['Member']).Member, users['outsider'].id)
        outsider.role='admin'
    assert (await c['outsider'].get('/api/v1/settings/model-services/'+saved['id'])).status_code==404
    assert (await c['outsider'].put('/api/v1/settings/model-routing',json=route(saved))).status_code==404
    assert (await c['admin'].post('/api/v1/settings/model-services', json=payload(),headers={'X-CSRF-Token':'wrong'})).status_code==403
    key=settings.model_key_file.read_bytes();settings.model_key_file.unlink()
    response=await c['admin'].patch('/api/v1/settings/model-services/'+saved['id'], json={**payload(),'apiKey':'','expectedRevision':1})
    assert response.status_code==503 and SECRET not in response.text
    settings.model_key_file.write_bytes(key);settings.model_key_file.chmod(0o600)
    # A newly created company never inherits server credentials.
    data=(await c['outsider'].get('/api/v1/settings/model-routing')).json()
    assert data['source']=='database' and data['environment'] is None
    assert (await c['outsider'].post('/api/v1/settings/model-services/import-environment')).status_code==409
    assert (await c['admin'].get('/api/v1/settings/model-routing')).json()['source']=='environment'
    await c['admin'].put('/api/v1/settings/model-routing',json={'expectedRevision':0,'assistant':None,'report':'follow','asr':None})
    assert (await c['admin'].get('/api/v1/settings/model-routing')).json()['source']=='database'


async def test_bound_revision_survives_edit_and_retry_current_config_isolated(setup):
    settings,sessions,users,c=setup
    first=await create(c['admin']);await c['admin'].put('/api/v1/settings/model-routing',json=route(first))
    sent=await send(c['employee'],'配置恢复样本')
    claimed=await claim(sessions,users['employee'].id)
    async with sessions.begin() as db:
        live=await db.get(Job,claimed.id);binding=await bind_job(db,live,settings)
    changed=await c['admin'].patch('/api/v1/settings/model-services/'+first['id'],json={**payload(url='https://second.example/v1'),'apiKey':'replacement-test-key','expectedRevision':1})
    assert changed.status_code==200
    async with sessions() as db:
        config,key=await resolve_bound(db,settings,users['employee'].company_id,binding,'assistant')
        assert config['baseUrl']=='https://example.com/v1' and key==SECRET and config['parameters']=={}
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(claimed,sessions,settings,saver,model=model('旧版本',fail_once=True))
        response=await c['employee'].post('/api/v1/jobs/'+claimed.id+'/retry',json={})
        assert response.status_code==200
        retry=await claim(sessions,users['employee'].id)
        async with sessions() as db:
            assert (await db.get(Job,retry.id)).model_binding==binding
        await process_job(retry,sessions,settings,saver,model=model('仍旧版本',fail_once=True))
        await c['employee'].post('/api/v1/jobs/'+claimed.id+'/retry',json={'useCurrentConfig':True})
        retry=await claim(sessions,users['employee'].id)
        await process_job(retry,sessions,settings,saver,model=model('新版本'))
        async with sessions() as db:
            live=await db.get(Job,retry.id)
            assert live.state=='succeeded' and live.config_attempt==1
            assert live.model_binding['assistant']['revision']==2
            assert SECRET not in json.dumps(live.model_binding)


async def test_parameter_and_network_boundaries(setup,monkeypatch):
    settings,*_=setup
    for url in ('http://example.com/v1','https://u:p@example.com/v1','https://example.com/v1?x=1','https://example.com/#frag','https://example.com/\n'):
        with pytest.raises(ProviderError): normalize_url(url,settings)
    assert normalize_url('https://EXAMPLE.com/v1/',settings)=='https://example.com/v1'
    assert not allowed_address('127.0.0.1') and not allowed_address('::ffff:127.0.0.1') and not allowed_address('169.254.169.254')
    for data in ({'max_tokens':200},{'thinking':{'headers':{}}},{'constructor':{}},{'reasoning_effort':'${secret}'},{'timeout':100}):
        with pytest.raises(ValueError): parameters(data)
    assert request_options({'presets':[],'selectedPresetId':None})=={}
    loop=asyncio.get_running_loop();connections=[]
    async def resolve(*args,**kwargs): return [(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('127.0.0.1',443))]
    monkeypatch.setattr(loop,'getaddrinfo',resolve)
    backend=CheckedBackend(settings)
    with pytest.raises(ProviderError): await backend.connect_tcp('example.com',443)
    async def public(*args,**kwargs): return [(2,1,6,'',('8.8.8.8',443))]
    monkeypatch.setattr(loop,'getaddrinfo',public)
    async def connect(self,host,port,*args): connections.append(host);return 'socket'
    monkeypatch.setattr('httpcore._backends.auto.AutoBackend.connect_tcp',connect)
    assert await backend.connect_tcp('example.com',443)=='socket' and connections==['8.8.8.8']


class Bytes(httpx.AsyncByteStream):
    def __init__(self,value):self.value=value
    async def __aiter__(self):yield self.value


async def test_streamed_tools_are_complete_and_audio_protocols_are_distinct(setup,monkeypatch):
    settings,*_=setup
    bodies=[];mode=['complete']
    def response(request):
        bodies.append(request)
        if request.url.path.endswith('/audio/transcriptions'):
            assert 'multipart/form-data' in request.headers['content-type']
            assert b'name="file"' in request.content and b'RIFF' in request.content
            return httpx.Response(200,json={'text':'今天的工作已经完成'})
        body=json.loads(request.content)
        if body.get('messages',[{}])[0].get('content',[{}])[0].get('type')=='input_audio' if isinstance(body.get('messages',[{}])[0].get('content'),list) else False:
            return httpx.Response(200,json={'choices':[{'message':{'content':'今天的工作已经完成'}}]})
        chunks=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call1','function':{'name':'probe_','arguments':'{"value":'}}]}}]}, {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'echo','arguments':'"测试成功"}'}}]},'finish_reason':'tool_calls'}]}]
        data=''.join('data: '+json.dumps(x,ensure_ascii=False)+'\n\n' for x in chunks)
        if mode[0]=='complete':data+='data: [DONE]\n\n'
        return httpx.Response(200,stream=Bytes(data.encode()))
    monkeypatch.setattr('paa_server.model_provider.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(response)))
    config={'baseUrl':'https://example.com/v1','model':'test','streaming':True,'protocol':'chat','parameters':{}}
    result=await chat(settings,config,SECRET,[{'role':'user','content':'test'}])
    assert result['choices'][0]['message']['tool_calls'][0]['function']=={'name':'probe_echo','arguments':'{"value":"测试成功"}'}
    mode[0]='incomplete'
    with pytest.raises(ProviderError,match='未完整结束'):await chat(settings,config,SECRET,[{'role':'user','content':'test'}])
    wav=(Path(__file__).parents[2]/'src/python/paa_server/assets/probe-zh.wav').read_bytes()
    for protocol in ('transcriptions','qwen-asr'):
        transcript,_=await transcribe(settings,{**config,'protocol':protocol},SECRET,wav)
        assert '工作' in transcript
    assert '/audio/transcriptions' in str(bodies[-2].url) and '/chat/completions' in str(bodies[-1].url)


@pytest.mark.parametrize('streaming', [False, True])
async def test_actual_bounded_harness_uses_frozen_service_and_reserves_each_call(setup,monkeypatch,streaming):
    settings,sessions,users,c=setup
    saved=await create(c['admin']); routing=route(saved);routing['assistant']['streaming']=streaming
    await c['admin'].put('/api/v1/settings/model-routing',json=routing)
    calls=[]
    async def response(request):
        body=json.loads(request.content);calls.append((str(request.url),body))
        assert request.headers['Authorization']=='Bearer '+SECRET
        assert 'enable_thinking' not in body and body['stream']==streaming and body['max_tokens']<=4000
        if len(calls)==1:
            await c['admin'].patch('/api/v1/settings/model-services/'+saved['id'],json={**payload(url='https://new.example/v1'),'apiKey':'new-test-secret','expectedRevision':1})
            message={'role':'assistant','content':'','tool_calls':[{'id':'progress-test','type':'function','function':{'name':'propose_progress','arguments':json.dumps({'title':'真实预算路径','summary':'受控响应测试','status':'in_progress','blocker':'','next_step':'','work_id':None})}}]}
            finish='tool_calls'
        else:
            message={'role':'assistant','content':'已整理，等待确认。'};finish='stop'
        if streaming:
            delta=dict(message)
            if 'tool_calls' in delta: delta['tool_calls'][0]['index']=0
            raw='data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n'
            return httpx.Response(200,stream=Bytes(raw.encode()))
        return httpx.Response(200,json={'choices':[{'message':message,'finish_reason':finish}], 'usage':{'prompt_tokens':120,'completion_tokens':30,'total_tokens':150}})
    monkeypatch.setattr('paa_server.model_provider.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(response)))
    sent=await send(c['employee'],'今天完成初稿')
    job=await claim(sessions,users['employee'].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job,sessions,settings,saver)
    result=(await c['employee'].get('/api/v1/messages/'+sent['messageId'])).json()
    assert result['job']['state']=='succeeded',result['job']
    assert len(result['suggestions'])==1 and all(url=='https://example.com/v1/chat/completions' for url,_ in calls)
    assert len(calls)==2
    async with sessions() as db:
        usages=(await db.scalars(select(ModelUsage).where(ModelUsage.job_id==job.id))).all()
        assert len(usages)==2 and all(u.kind=='assistant' for u in usages)
        from sqlalchemy import text
        blobs=(await db.execute(text('SELECT blob FROM checkpoint_blobs WHERE thread_id LIKE :prefix'),{'prefix':job.company_id+':%'})).all()
        assert not any(SECRET.encode() in bytes(b[0]) for b in blobs if b[0] is not None)


async def test_admin_probe_and_directory_validate_real_capabilities_without_business_writes(setup,monkeypatch):
    settings,sessions,users,c=setup
    paths=[]
    def response(request):
        paths.append(request.url.path)
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'controlled-chat'}]})
        body=json.loads(request.content)
        if body.get('tool_choice'):
            message={'role':'assistant','content':'','tool_calls':[{'id':'echo1','type':'function','function':{'name':'probe_echo','arguments':'{"value":"测试成功"}'}}]};finish='tool_calls'
        else:
            message={'role':'assistant','content':'红色' if isinstance(body['messages'][0]['content'],list) else '测试成功'};finish='stop'
        if body['stream']:
            delta=dict(message)
            if 'tool_calls' in delta:delta['tool_calls'][0]['index']=0
            return httpx.Response(200,stream=Bytes(('data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode()))
        return httpx.Response(200,json={'choices':[{'message':message,'finish_reason':finish}]})
    monkeypatch.setattr('paa_server.model_provider.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(response)))
    body={**payload(),'draftVersion':'draft-1','modelId':'chat','purpose':'assistant'}
    directory=await c['admin'].post('/api/v1/settings/model-services/models',json=body)
    assert directory.status_code==200 and directory.json()['models']==['controlled-chat']
    test=await c['admin'].post('/api/v1/settings/model-services/test',json=body)
    assert test.status_code==200,test.text
    assert all(x['state']=='passed' for x in test.json()['checks'])
    assert SECRET not in test.text and test.json()['usage'] is None
    async with sessions() as db:
        from paa_server.models import Message,WorkItem,Report,ModelCheck
        for table in (Message,WorkItem,Report,Job):
            assert not (await db.scalars(select(table).where(table.company_id==users['admin'].company_id))).all()
        assert len((await db.scalars(select(ModelUsage).where(ModelUsage.company_id==users['admin'].company_id))).all())==4
        assert len((await db.scalars(select(ModelCheck).where(ModelCheck.company_id==users['admin'].company_id))).all())==1


def probe_body(saved, *, draft_key='', purpose='assistant'):
    return {
        'name': saved['name'], 'baseUrl': saved['baseUrl'], 'apiKey': draft_key,
        'models': [dict(model, streaming=False) for model in saved['models']],
        'expectedRevision': saved['revision'], 'serviceId': saved['id'],
        'modelId': 'audio' if purpose == 'asr' else 'chat',
        'purpose': purpose, 'draftVersion': 'controlled-probe',
    }


def probe_response(request):
    body = json.loads(request.content)
    if body.get('tool_choice'):
        message = {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'echo1', 'type': 'function', 'function': {'name': 'probe_echo', 'arguments': '{"value":"测试成功"}'}}]}
        reason = 'tool_calls'
    else:
        message = {'role': 'assistant', 'content': '红色' if isinstance(body['messages'][0]['content'], list) else '测试成功'}
        reason = 'stop'
    return httpx.Response(200, json={'choices': [{'message': message, 'finish_reason': reason}]})


@pytest.mark.parametrize(('revoke_after', 'draft_key'), [(1, ''), (2, 'controlled-draft-key'), (3, '')])
async def test_probe_stops_unissued_calls_after_saved_service_revoked(setup, monkeypatch, revoke_after, draft_key):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    calls = []

    async def response(request):
        calls.append(request)
        assert request.headers['Authorization'] == 'Bearer ' + (draft_key or SECRET)
        if len(calls) == revoke_after:
            removed = await clients['admin'].request('DELETE', '/api/v1/settings/model-services/' + saved['id'], json={'expectedRevision': saved['revision']})
            assert removed.status_code == 200
        return probe_response(request)

    monkeypatch.setattr('paa_server.model_provider.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    response = await clients['admin'].post('/api/v1/settings/model-services/test', json=probe_body(saved, draft_key=draft_key))
    assert response.status_code == 200
    checks = response.json()['checks']
    assert len(calls) == revoke_after
    assert [check['state'] for check in checks] == (['passed', 'failed', 'untested'] if revoke_after == 1 else ['passed', 'passed', 'failed'])
    assert next(check for check in checks if check['state'] == 'failed')['code'] == 'revoked'


async def test_probe_keeps_original_revision_after_service_edit(setup, monkeypatch):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    calls = []

    async def response(request):
        calls.append(request)
        assert str(request.url) == saved['baseUrl'] + '/chat/completions'
        assert request.headers['Authorization'] == 'Bearer ' + SECRET
        assert json.loads(request.content)['model'] == 'controlled-chat'
        if len(calls) == 1:
            changed = payload(url='https://changed.example/v1')
            changed.update(apiKey='controlled-replacement-key', expectedRevision=1)
            changed['models'][0]['model'] = 'replacement-model'
            result = await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json=changed)
            assert result.status_code == 200 and result.json()['revision'] == 2
        return probe_response(request)

    monkeypatch.setattr('paa_server.model_provider.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    response = await clients['admin'].post('/api/v1/settings/model-services/test', json=probe_body(saved))
    assert response.status_code == 200
    assert len(calls) == 4 and response.json()['revision'] == 1
    assert all(check['state'] == 'passed' for check in response.json()['checks'])


@pytest.mark.parametrize('protocol', ['transcriptions', 'qwen-asr'])
async def test_asr_probe_checks_revocation_immediately_before_outbound(setup, monkeypatch, protocol):
    from paa_server import model_services
    settings, sessions, users, clients = setup
    body = payload()
    body['models'][1]['protocol'] = protocol
    saved = await create(clients['admin'], body)
    calls = []
    reserve = model_services.reserve_probe

    async def reserve_then_revoke(*args):
        usage_id = await reserve(*args)
        removed = await clients['admin'].request('DELETE', '/api/v1/settings/model-services/' + saved['id'], json={'expectedRevision': saved['revision']})
        assert removed.status_code == 200
        return usage_id

    def response(request):
        calls.append(request)
        return httpx.Response(200, json={'text': '今天的工作已经完成', 'choices': [{'message': {'content': '今天的工作已经完成'}}]})

    monkeypatch.setattr(model_services, 'reserve_probe', reserve_then_revoke)
    monkeypatch.setattr('paa_server.model_provider.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    response = await clients['admin'].post('/api/v1/settings/model-services/test', json=probe_body(saved, purpose='asr'))
    assert response.status_code == 200
    assert calls == []
    assert response.json()['checks'][0]['state'] == 'failed'
    assert response.json()['checks'][0]['code'] == 'revoked'


async def test_explicit_environment_import_preserves_behavior_and_clear_never_falls_back(setup):
    from paa_server.model_services import import_environment, routing_dto
    settings,sessions,users,c=setup
    configured=replace(settings,agent_base_url='https://example.com/v1',agent_key=SECRET,agent_model='legacy',agent_options={'enable_thinking':False},asr_base_url='https://example.com/v1',asr_key=SECRET,asr_model='legacy-asr')
    async with sessions.begin() as db:
        result=await import_environment(db,users['admin'],configured)
        assert result['source']=='database' and result['report']=='follow'
        services=(await db.scalars(select(ModelService).where(ModelService.company_id==users['admin'].company_id))).all()
        assert len(services)==1 and len(services[0].models)==2
        assert all(not m['streaming'] for m in services[0].models)
        assert result['asr']['serviceId']==result['assistant']['serviceId']
    sent=await send(c['employee'])
    job=await claim(sessions,users['employee'].id)
    async with sessions.begin() as db:
        live=await db.get(Job,job.id);binding=await bind_job(db,live,configured)
        config,key=await resolve_bound(db,configured,job.company_id,binding,'assistant')
        assert key==SECRET and config['parameters']=={'enable_thinking':False} and not config['streaming']
    assert (await c['admin'].put('/api/v1/settings/model-routing',json={'expectedRevision':1,'assistant':None,'report':None,'asr':None})).status_code==200
    async with sessions.begin() as db:
        live=await db.get(Job,job.id);live.model_binding=None
        assert (await bind_job(db,live,configured))['assistant'] is None


async def test_revocation_blocks_bound_call_and_new_company_does_not_inherit_environment(setup):
    settings,sessions,users,c=setup
    saved=await create(c['admin']);await c['admin'].put('/api/v1/settings/model-routing',json=route(saved))
    await send(c['employee']);job=await claim(sessions,users['employee'].id)
    async with sessions.begin() as db:
        live=await db.get(Job,job.id);binding=await bind_job(db,live,settings)
    await c['admin'].put('/api/v1/settings/model-routing',json={'expectedRevision':1,'assistant':None,'report':None,'asr':None})
    assert (await c['admin'].request('DELETE','/api/v1/settings/model-services/'+saved['id'],json={'expectedRevision':1})).status_code==200
    async with sessions() as db:
        with pytest.raises(ProviderError,match='撤销'):await resolve_bound(db,settings,job.company_id,binding,'assistant')
    await send(c['outsider']);other=await claim(sessions,users['outsider'].id)
    async with sessions.begin() as db:
        live=await db.get(Job,other.id)
        binding=await bind_job(db,live,replace(settings,agent_base_url='https://example.com/v1',agent_key=SECRET))
        assert binding['assistant'] is None and binding['source']=='database'


async def test_directory_official_pagination_stays_same_origin_and_rejects_response_compression(setup,monkeypatch):
    from paa_server.model_provider import catalog
    settings,*_=setup
    calls=[]
    def response(request):
        calls.append(request)
        assert request.url.host=='space.cn-beijing.maas.aliyuncs.com'
        assert request.url.path=='/api/v1/models'
        return httpx.Response(200,json={'output':{'models':[{'model':'model-'+str(i)} for i in range(100)] if request.url.params['page_no']=='1' else [{'model':'last'}]}})
    monkeypatch.setattr('paa_server.model_provider.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(response)))
    result=await catalog(settings,'https://space.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',SECRET)
    assert len(calls)==2 and len(result['models'])==101
    async def compressed(self,request):return httpx.Response(200,headers={'content-encoding':'gzip'},stream=Bytes(b'not-inflated'))
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',compressed)
    transport=SafeTransport(settings)
    with pytest.raises(ProviderError,match='压缩'):await transport.handle_async_request(httpx.Request('GET','https://example.com/v1/models'))
    await transport.aclose()


async def test_master_key_pair_restore_and_missing_key_cannot_be_reinitialized(setup,monkeypatch):
    from paa_server.cli import prepare_model_key
    settings,sessions,users,c=setup
    saved=await create(c['admin'])
    original=settings.model_key_file.read_bytes()
    initialize_key(settings.model_key_file)
    assert settings.model_key_file.read_bytes()==original
    async with sessions() as db:
        revision=await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id==saved['id']))
    settings.model_key_file.unlink()
    monkeypatch.setattr('paa_server.cli.Settings',lambda:settings)
    with pytest.raises(SecretUnavailable):await prepare_model_key()
    assert not settings.model_key_file.exists()
    settings.model_key_file.write_bytes(b'x'*32);settings.model_key_file.chmod(0o600)
    with pytest.raises(SecretUnavailable):decrypt(settings.model_key_file,revision.credential,users['admin'].company_id,saved['id'],1)
    response = await c['admin'].patch('/api/v1/settings/model-services/'+saved['id'], json={**payload(), 'apiKey':'replacement-after-key-loss', 'expectedRevision':1})
    assert response.status_code == 503
    settings.model_key_file.write_bytes(original)
    assert decrypt(settings.model_key_file,revision.credential,users['admin'].company_id,saved['id'],1)==SECRET


async def test_failed_probe_does_not_claim_other_capabilities_or_reveal_remote_errors(setup,monkeypatch):
    settings,sessions,users,c=setup
    requests=[]
    def response(request):
        requests.append(request)
        return httpx.Response(401,json={'error':{'message':'Remote accidentally echoed '+SECRET},'usage':{'authorization':SECRET}})
    monkeypatch.setattr('paa_server.model_provider.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(response)))
    result=await c['admin'].post('/api/v1/settings/model-services/test',json={**payload(),'draftVersion':'failure','modelId':'chat','purpose':'assistant'})
    assert result.status_code==200
    check=result.json()
    assert check['checks'][0]['code']=='authentication' and all(x['state']=='untested' for x in check['checks'][1:])
    assert SECRET not in result.text and len(requests)==1


async def test_report_current_config_attempt_preserves_saved_draft_as_new_candidate(setup,monkeypatch):
    from paa_server import worker
    from paa_server.models import Report
    settings,sessions,users,c=setup
    saved=await create(c['admin']);await c['admin'].put('/api/v1/settings/model-routing',json=route(saved))
    actor=users['employee']
    async with sessions.begin() as db:
        report=Report(company_id=actor.company_id,owner_id=actor.id,kind='daily',period='2026-09-12',period_end='2026-09-12',timezone='Asia/Shanghai')
        db.add(report);await db.flush()
        job=Job(company_id=actor.company_id,owner_id=actor.id,kind='report',target_id=report.id,base_revision=1)
        db.add(job);await db.flush();job_id=job.id;report_id=report.id
    invoke=worker.invoke_harness
    async def after_saved(*args,**kwargs):
        await invoke(*args,**kwargs)
        raise RuntimeError('Controlled failure after saved report')
    monkeypatch.setattr(worker,'invoke_harness',after_saved)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(await claim(sessions,actor.id),sessions,settings,saver,model=model('原报告','report'))
        async with sessions() as db:assert (await db.get(Job,job_id)).result['reportSaved']
        assert (await c['employee'].post('/api/v1/jobs/'+job_id+'/retry',json={'useCurrentConfig':True})).status_code==200
        monkeypatch.setattr(worker,'invoke_harness',invoke)
        await process_job(await claim(sessions,actor.id),sessions,settings,saver,model=model('新候选','report'))
    async with sessions() as db:
        report=await db.get(Report,report_id)
        assert report.content['completed']=='原报告' and report.candidate['content']['completed']=='新候选' and report.published_revision==0


async def test_company_probe_concurrency_and_quota_are_bounded(setup,monkeypatch):
    from paa_server.model_services import reserve_probe
    settings,sessions,users,c=setup
    entered,release=asyncio.Event(),asyncio.Event()
    async def response(request):
        entered.set();await release.wait()
        return httpx.Response(200,json={'data':[]})
    monkeypatch.setattr('paa_server.model_provider.client',lambda settings:httpx.AsyncClient(transport=httpx.MockTransport(response)))
    body={**payload(),'draftVersion':'busy','modelId':'chat'}
    pending=asyncio.create_task(c['admin'].post('/api/v1/settings/model-services/models',json=body))
    await asyncio.wait_for(entered.wait(),2)
    try:
        result=await c['admin'].post('/api/v1/settings/model-services/test',json=body)
        assert result.status_code==409
    finally:
        release.set()
        assert (await pending).status_code==200
    limited=replace(settings,daily_calls=1)
    await reserve_probe(sessions,limited,users['admin'])
    with pytest.raises(ProviderError,match='额度'):await reserve_probe(sessions,limited,users['admin'])
