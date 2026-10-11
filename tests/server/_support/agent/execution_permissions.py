"""Shared controlled fixtures extracted from test_execution_permissions."""
from app.tasks.context import RunContext
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import Judge
from _support.http.company import keyed


SETTINGS_PATH = '/api/v1/assistant/execution-settings'


async def set_mode(client, mode, *, confirmed=True):
    previous = (await client.get(SETTINGS_PATH)).json()
    result = await client.patch(SETTINGS_PATH, json={'executionMode': mode, 'fullAccessConfirmed': confirmed, 'expectedRevision': previous['modeRevision']})
    assert result.status_code == 200, result.text
    return result.json()


async def mode_runtime(setup, mode, text='创建工作：整理需求', who='employee'):
    settings, sessions, users, clients = setup
    await set_mode(clients[who], mode)
    response = await clients[who].post('/api/v1/messages', json={'newConversation': True, 'text': text, 'executionMode': mode, 'fullAccessConfirmed': mode == 'full'}, headers=keyed())
    assert response.status_code == 202, response.text
    sent = response.json()
    job = await claim(sessions, users[who].id)
    return RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, intent_model=Judge()), sent
