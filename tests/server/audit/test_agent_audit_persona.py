"""Current-prompt counterpart; original legacy persona failures remain unchanged."""
import json
import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select, text
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from _support.http.company import keyed
from _support.http.model_services import create, payload, route
from _support.agent.task_retry import fast_nodes
from _support.http.agent_audit_api import evidence

@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['admin', 'employee'])
@pytest.mark.parametrize('persona', ['dabao', 'professional'])
async def test_current_persona_freezes_across_502_401_and_manual_retry(setup, monkeypatch, fast_nodes, role, persona):
    settings, sessions, users, clients = setup
    client = clients[role]
    from _support.http.model_services import payload
    body = payload()
    body['models'][0]['streaming'] = False
    service = await create(clients['admin'], body)
    routing = route(service)
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 200
    sent = (await client.post('/api/v1/messages', json={'newConversation': True, 'personaId': persona, 'text': '今天忙得脑子打结了'}, headers=keyed())).json()
    path = '/api/v1/conversations/' + sent['conversationId']
    conversation = (await client.get(path)).json()
    other = 'professional' if persona == 'dabao' else 'dabao'
    await client.patch(path, json={'personaId': other, 'expectedRevision': conversation['revision']})
    calls = []
    from app.agent.prompts.persona import runtime_persona_prompt
    marker = runtime_persona_prompt(persona)
    answer = '脑内标签页开太多了。先说最卡的一件，我们一件件拆。' if persona == 'dabao' else '先处理最卡的一件。现在是哪项任务？'
    async def response(request):
        body = json.loads(request.content)
        calls.append((str(request.url), body))
        system = '\n'.join(str(item['content']) for item in body['messages'] if item['role'] == 'system')
        if body.get('tools'):
            assert marker in system
            assert runtime_persona_prompt(other) not in system
            assert ('管理员：管理本人工作' if role == 'admin' else '员工：管理本人工作') in system
            if len(calls) == 1:
                return httpx.Response(502, json={'error': {'message': 'controlled temporary error'}})
            if len(calls) == 2:
                return httpx.Response(401, json={'error': {'message': 'controlled response failure'}})
            from _support.agent.fakes import wire_completion
            message = wire_completion(answer)
        else:
            raise AssertionError('Ordinary persona response must not make a second review call')
        return httpx.Response(200, json={'choices': [{'message': message, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    job = await claim(sessions, users[role].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver)
        failed = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
        assert failed['job']['state'] == 'awaiting_retry', failed
        assert len(calls) == 2
        # Retry retains message persona but deliberately uses the latest model binding.
        changed = await clients['admin'].patch('/api/v1/settings/model-services/' + service['id'], json={**payload(url='https://latest.example/v1'), 'models': body['models'], 'apiKey': 'controlled-latest', 'expectedRevision': 1})
        assert changed.status_code == 200
        assert (await client.post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={})).status_code == 200
        retried = await claim(sessions, users[role].id)
        await process_job(retried, sessions, settings, saver)
    result = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['job']['state'] == 'awaiting_input' and result['reply'] == answer, result
    assert result['actions'] == [] and result['drafts'] == [] and result['suggestions'] == []
    assert len(calls) == 3 and all(url.startswith('https://latest.example/') for url, _ in calls[2:])
    async with sessions() as db:
        assert (await db.get(Message, sent['messageId'])).persona_id == persona
        assert (await db.get(Conversation, sent['conversationId'])).persona_id == other
        assert (await db.get(Job, sent['jobId'])).model_binding['assistant']['revision'] == 2
        threads = (await db.scalars(text('SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix': users[role].company_id + ':%'})).all()
        assert threads
        assert all((':persona:dabao:' in thread) == (persona == 'dabao') for thread in threads)
        assert not (await client.get('/api/v1/work-items')).json()['items']

    evidence('persona-retry-' + persona + '-' + role, {'providerStatuses': [502, 401, 200], 'calls': len(calls), 'taskPersona': persona, 'conversationPersona': other, 'latestBindingRevision': 2, 'finalState': result['job']['state'], 'reply': result['reply'], 'actions': len(result['actions']), 'drafts': len(result['drafts']), 'suggestions': len(result['suggestions'])})
