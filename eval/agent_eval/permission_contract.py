"""Owned local object-level HTTP/tool permission checks; no model invocation."""
import json
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
from .adapters import environment, isolate_actor
from .evidence import write, seal


async def evaluate(metadata_path, directory):
    import httpx
    _, metadata, state = environment(metadata_path)
    directory.mkdir(parents=True, exist_ok=False)
    local, state = await isolate_actor(metadata_path, directory, metadata, state)
    clients = {}
    fixtures = []
    observations = []
    async def login(role):
        actor = state['users'][role]
        client = httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}, timeout=20)
        response = await client.post('/api/v1/auth/login', json={'username': actor['username'], 'password': actor['password']})
        response.raise_for_status(); client.headers['X-CSRF-Token'] = response.json()['csrf']
        clients[role] = client
        return client
    try:
        reader = await login('employee')
        for role in ('peer', 'outsider'):
            client = await login(role)
            response = await client.post('/api/v1/work-items', headers={'Idempotency-Key': __import__('uuid').uuid4().hex}, json={'title': '受保护对象-' + role, 'summary': 'PRIVATE-SYNTHETIC-' + role, 'status': 'in_progress'})
            response.raise_for_status(); created = response.json()
            response = await client.get('/api/v1/work-items/' + created['id']); response.raise_for_status(); before = response.json()
            fixtures.append((role, before))
            for method, suffix, body in [('GET', '', None), ('POST', '/progress', {'title': '不应写入', 'status': 'done', 'expectedRevision': before['revision']}), ('DELETE', '', {'expectedRevision': before['revision']})]:
                response = await reader.request(method, '/api/v1/work-items/' + before['id'] + suffix, json=body)
                observations.append({'id': role + ':' + method, 'status': 'PASS' if response.status_code in (403, 404) and 'PRIVATE-SYNTHETIC' not in response.text else 'FAIL', 'httpStatus': response.status_code, 'response': response.json()})
        from app.core.config import Settings
        from app.db.session import database
        from app.db.base import now
        from app.modules.messages.models import Message
        from app.tasks.models import Job
        from app.tasks.context import RunContext
        from app.agent.tools.business.work import get_work_item
        settings = Settings(); engine, sessions = database(settings)
        actor = state['users']['employee']
        try:
            async with sessions.begin() as db:
                message = Message(owner_id=actor['id'], company_id=actor['companyId'], text='controlled tool authorization fixture; not a model run')
                db.add(message); await db.flush()
                job = Job(owner_id=actor['id'], company_id=actor['companyId'], kind='message', target_id=message.id, state='running', fence=1, lease_until=now()+timedelta(minutes=5))
                db.add(job); await db.flush()
                job_id, message_id = job.id, message.id
            (directory / 'accepted.jsonl').write_text(json.dumps({'receipt': {'jobId': job_id, 'messageId': message_id}}) + '\n')
            context = RunContext(actor['id'], actor['companyId'], job_id, 1, sessions, settings)
            for role, before in fixtures:
                raw = await get_work_item.coroutine(work_id=before['id'], runtime=SimpleNamespace(context=context))
                result = json.loads(raw)
                observations.append({'id': role + ':tool-get-work', 'status': 'PASS' if result.get('state') == 'failed' and 'PRIVATE-SYNTHETIC' not in raw else 'FAIL', 'result': result})
            # Controlled API cancellation of the owned leased fixture: tests the
            # same cleanup endpoint without adding a billable model request.
            response = await reader.post('/api/v1/jobs/' + job_id + '/cancel', json={'expectedAttempt': 0, 'expectedFence': 1})
            observed = await reader.get('/api/v1/jobs/' + job_id)
            observations.append({'id': 'owned-cancel', 'fixture': 'directly seeded leased job, no provider call', 'status': 'PASS' if response.status_code == 200 and observed.json().get('state') == 'cancelled' else 'FAIL', 'httpStatus': response.status_code, 'after': observed.json().get('state')})
        finally:
            await engine.dispose()
        for role, before in fixtures:
            response = await clients[role].get('/api/v1/work-items/' + before['id']); response.raise_for_status()
            observations.append({'id': role + ':no-mutation', 'status': 'PASS' if response.json() == before else 'FAIL', 'before': before, 'after': response.json()})
        value = {'execution': 'contract/replay', 'providerCalls': 0, 'evidenceAvailable': ['http', 'tool', 'database-before-after', 'cancel'], 'checks': observations, 'isolation': 'same-company peer and different-company outsider, new owned tenant partitions', 'metadata': str(local)}
        write(directory / 'result.json', seal(value))
        return value
    finally:
        for client in clients.values():
            await client.post('/api/v1/auth/logout', json={}); await client.aclose()
