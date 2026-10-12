"""Shared controlled fixtures extracted from test_agent_budget_flow."""
import json
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from app.tasks.processing.handlers import process_job
from _support.http.company import send


def provider(monkeypatch, respond):
    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}, 'streaming': True}, 'test'
    async def binding(*args):
        return {'assistant': {'model': 'controlled'}}
    async def noop(*args):
        pass
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    monkeypatch.setattr('app.modules.model_services.bindings.bind_job', binding)
    monkeypatch.setattr('app.modules.model_services.bindings.freeze_capacities', noop)
    monkeypatch.setattr('app.integrations.models.chat.chat', respond)


def response(content='', calls=None):
    value = {'role': 'assistant', 'content': content}
    if calls:
        value['tool_calls'] = [{'id': identifier, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}} for identifier, name, args in calls]
    return {'choices': [{'message': value, 'finish_reason': 'tool_calls' if calls else 'stop'}]}


async def run(setup, text='请按要求查询', who='employee'):
    settings, sessions, users, clients = setup
    sent = await send(clients[who], text)
    job = await claim(sessions, users[who].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver)
    result = (await clients[who].get('/api/v1/messages/' + sent['messageId'])).json()
    async with sessions() as db:
        stored = (await db.get(Job, job.id)).result
    return result, stored
