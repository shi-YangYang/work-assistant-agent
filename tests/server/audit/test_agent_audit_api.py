"""Spec 059 authentication coverage for the frozen Agent-related HTTP surface."""
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/company/web-acceptance/agent-audit'))
from faults import evidence
from fixed import inventory

pytestmark = pytest.mark.asyncio


async def test_all_agent_routes_reject_unauthenticated_requests(setup):
    app = setup[3]['employee']._transport.app
    routes = inventory()['apis']
    expected = {(route['method'], route['path']) for route in routes}
    assert expected and len(expected) == len(routes)
    observed = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                headers={'Origin': 'http://test'}) as client:
        for route in routes:
            parameters = {'view': 'work', 'action': 'confirm', 'choice': 'confirm'}
            path = re.sub(r'\{([^}]+)\}', lambda match: parameters.get(match[1], str(uuid4())), route['path'])
            response = await client.request(route['method'], path)
            observed.append({'method': route['method'], 'path': route['path'], 'status': response.status_code})
            assert response.status_code == 401, observed[-1]
            assert response.json()['error']['message']
    evidence('api-unauthenticated', {'requests': observed, 'assertion': 'all routes reject before revealing resources'})
    assert {(row['method'], row['path']) for row in observed} == expected
    assert len(observed) == len(expected)


async def test_record_request_boundaries_preserve_real_work_and_report(setup):
    from app.modules.reports.models import Report
    from _support.http.company import keyed, send
    from _support.http.core_scope_coverage import snapshot
    from _support.materials.documents import upload
    from _support.work.work_records import create

    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    root = '/api/v1/work-items/' + work['id']
    update = await client.post(root + '/updates', json={'expectedRevision': 1, 'text': '受控原始进展'}, headers=keyed())
    assert update.status_code == 201
    update_id = update.json()['update']['id']
    attachment = await upload(client, 'scope.txt', b'controlled-original-material')
    added = await client.post(root + '/materials', json={'expectedRevision': 2, 'materials': [{'attachmentId': attachment['id']}]}, headers=keyed())
    assert added.status_code == 201
    material_id = added.json()['materialIds'][0]
    sent = await send(client, '受控私有任务')
    async with sessions.begin() as db:
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id,
                        kind='weekly', period='2026-10-09', period_end='2026-10-09', timezone='UTC',
                        content={'completed': '受控私有报告', 'ongoing': '', 'blockers': '', 'next': ''})
        db.add(report)
        await db.flush()
        report_id = report.id
    commands = [
        ('GET', root + '/updates', None),
        ('GET', root + '/materials', None),
        ('GET', root + '/materials/' + material_id, None),
        ('POST', root + '/updates', {'expectedRevision': 3, 'text': '不得新增'}),
        ('PATCH', root + '/updates/' + update_id, {'expectedRevision': 3, 'expectedUpdateRevision': 1, 'text': '不得更改'}),
        ('DELETE', root + '/updates/' + update_id, {'expectedRevision': 3, 'expectedUpdateRevision': 1}),
        ('POST', root + '/materials', {'expectedRevision': 3, 'materials': [{'attachmentId': attachment['id']}]}),
        ('DELETE', root + '/materials/' + material_id, {'expectedRevision': 3, 'expectedMaterialRevision': 1}),
        ('GET', '/api/v1/reports/' + report_id + '/sources', None),
        ('DELETE', '/api/v1/reports/' + report_id, {'expectedRevision': 1}),
        ('GET', '/api/v1/jobs/' + sent['jobId'] + '/events?version=2', None),
        ('POST', '/api/v1/jobs/' + sent['jobId'] + '/retry', {}),
    ]
    companies = [users['employee'].company_id, users['outsider'].company_id]
    before = await snapshot(sessions, companies)
    observed = []
    for role in ('peer', 'outsider'):
        for method, path, body in commands:
            response = await clients[role].request(method, path, json=body, headers=keyed())
            assert response.status_code == 404, (role, method, path, response.text)
            assert not any(marker in response.text for marker in ('受控原始进展', 'controlled-original-material', '受控私有报告', '受控私有任务'))
            observed.append({'role': role, 'method': method, 'path': path, 'status': 404})
    for method, path, body in commands:
        if body and 'expectedRevision' in body:
            response = await client.request(method, path, json={**body, 'expectedRevision': 99}, headers=keyed())
            assert response.status_code == 409, (method, path, response.text)
            observed.append({'role': 'owner-stale', 'method': method, 'path': path, 'status': 409})
    for path in (root + '/updates?start=-1', root + '/materials?limit=51', root + '/materials/' + material_id + '?revision=0',
                 '/api/v1/reports/' + report_id + '/sources?revision=0'):
        response = await client.get(path)
        assert response.status_code == 422, (path, response.text)
        observed.append({'role': 'owner-invalid', 'method': 'GET', 'path': path, 'status': 422})
    assert await snapshot(sessions, companies) == before
    materials = await client.get(root + '/materials')
    assert materials.status_code == 200 and [item['id'] for item in materials.json()['items']] == [material_id]
    item = await client.get(root + '/materials/' + material_id)
    assert item.status_code == 200 and item.json()['id'] == material_id
    updates = await client.get(root + '/updates')
    assert updates.status_code == 200 and updates.json()['items'][0]['text'] == '受控原始进展'
    evidence('record-api-boundaries', {'requests': observed, 'objectsAndJobsUnchanged': True,
                                      'normal': ['GET materials', 'GET material', 'GET updates']})


async def test_settings_team_and_creation_validation_boundaries(setup):
    from _support.http.company import keyed
    _, _, users, clients = setup
    client, admin = clients['employee'], clients['admin']
    memory = (await client.get('/api/v1/assistant/memory')).json()
    commands = [
        (client, 'PATCH', '/api/v1/assistant/memory/settings', {'expectedRevision': 99, 'enabled': False}, 409),
        (client, 'PATCH', '/api/v1/assistant/memory/settings', {'expectedRevision': 0, 'enabled': False, 'ownerId': users['peer'].id}, 422),
        (client, 'POST', '/api/v1/work-items', {'title': ''}, 422),
        (client, 'POST', '/api/v1/reports/generate', {'kind': 'invalid', 'date': '2026-10-09'}, 422),
        (admin, 'POST', '/api/v1/reports/generate', {'kind': 'weekly', 'date': '2026-10-09'}, 403),
        (admin, 'GET', '/api/v1/team/workspace/invalid', None, 404),
        (admin, 'GET', '/api/v1/team/details?metric=invalid', None, 422),
        (admin, 'GET', '/api/v1/team/report-obligations?cursor=-1', None, 422),
        (admin, 'GET', '/api/v1/team/members/' + users['employee'].id + '/messages?limit=101', None, 422),
        (admin, 'GET', '/api/v1/team/members/' + users['employee'].id + '/work?limit=21', None, 422),
    ]
    observed = []
    for actor, method, path, body, status in commands:
        response = await actor.request(method, path, json=body, headers=keyed())
        assert response.status_code == status, (method, path, response.text)
        observed.append({'role': 'owner' if actor is client else 'admin', 'method': method, 'path': path, 'status': status})
    for path in ('/api/v1/team', '/api/v1/team/details?metric=messages',
                 *['/api/v1/team/members/' + users['employee'].id + '/' + suffix for suffix in ('messages', 'work', 'reports')]):
        response = await client.get(path)
        assert response.status_code == 403, (path, response.text)
        observed.append({'role': 'employee', 'method': 'GET', 'path': path, 'status': 403})
    assert (await client.get('/api/v1/assistant/memory')).json() == memory
    assert (await client.get('/api/v1/work-items')).json()['items'] == []
    assert (await client.get('/api/v1/reports')).json()['items'] == []
    evidence('settings-team-api-boundaries', {'requests': observed, 'savedMemoryUnchanged': True,
                                             'noCreatedWorkOrReports': True})


async def test_agent_resource_reads_return_missing_without_server_errors(setup):
    clients = setup[3]
    observed = []
    for route in inventory()['apis']:
        if route['method'] != 'GET' or '{identifier}' not in route['path'] and '{message_id}' not in route['path']:
            continue
        path = re.sub(r'\{[^}]+\}', lambda match: '1' if match[0] == '{page}' else str(uuid4()), route['path'])
        if '/deliverables/' in path and '/files/' in path or '/uploads/' in path and '/pages/' in path:
            path += '?revision=1'
        client = clients['admin'] if path.startswith('/api/v1/team/') else clients['employee']
        response = await client.get(path)
        assert response.status_code == 404, (route['path'], response.status_code, response.text)
        assert response.json()['error']['message']
        observed.append({'method': 'GET', 'path': route['path'], 'status': 404})
    evidence('api-missing-resources', {'requests': observed, 'assertion': 'authenticated unknown resource is 404 without data'})
    assert len(observed) >= 25


async def test_message_creation_and_transcript_reject_foreign_real_conversation(setup):
    from _support.http.company import keyed, send
    _, _, _, clients = setup
    sent = await send(clients['employee'], '当前用户的私有消息')
    observed = []
    for role in ('peer', 'outsider', 'admin'):
        for body in ({'text': '不能插入', 'conversationId': sent['conversationId']},
                     {'text': '不能引用', 'replyTo': sent['messageId']}):
            response = await clients[role].post('/api/v1/messages', json=body, headers=keyed())
            assert response.status_code == 404, (role, response.text)
            observed.append({'role': role, 'method': 'POST', 'path': '/api/v1/messages', 'status': 404})
        response = await clients[role].patch('/api/v1/messages/' + sent['messageId'] + '/transcript',
                                            json={'text': '不能更正', 'expectedRevision': 0})
        assert response.status_code == 404, (role, response.text)
        observed.append({'role': role, 'method': 'PATCH', 'path': '/api/v1/messages/' + sent['messageId'] + '/transcript', 'status': 404})
    own = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert own['text'] == '当前用户的私有消息' and own['transcript'] == ''
    assert own['job']['state'] == 'queued'
    evidence('message-owner-boundaries', {'requests': observed, 'originalUnchanged': True})
