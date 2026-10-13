"""Shared text routing, legacy configuration and immutable job compatibility."""
from types import SimpleNamespace

import pytest
from app.modules.members.models import Member
from app.modules.model_services.bindings import bind_job, resolve_bound
from app.modules.model_services.models import ModelRouting
from _support.http.model_services import create, payload

pytestmark = pytest.mark.asyncio
PATH = '/api/v1/settings/model-routing'


@pytest.mark.parametrize('has_assistant', [True, False])
async def test_legacy_routes_share_one_text_model_and_keep_other_capabilities(setup, has_assistant):
    settings, sessions, users, clients = setup
    body = payload()
    body['models'][0]['reasoning'] = {'efforts': ['low', 'high'], 'initial': 'low'}
    body['models'] += [
        {**body['models'][0], 'id': 'old-report', 'model': 'old-report-model'},
        {'id': 'image', 'model': 'wan2.7-image', 'protocol': 'dashscope-image'},
    ]
    saved = await create(clients['admin'], body)
    choice = lambda model: {'serviceId': saved['id'], 'modelId': model}
    expected = choice('chat' if has_assistant else 'old-report')
    stored = {
        'assistant': choice('chat') if has_assistant else None,
        'report': {**choice('old-report'), 'parameters': {'temperature': .7}, 'explicitReasoning': True},
        'asr': choice('audio'), 'image': choice('image'),
    }
    async with sessions.begin() as db:
        db.add(ModelRouting(company_id=users['admin'].company_id, revision=3, choices=stored))
        member = await db.get(Member, users['employee'].id)
        member.reasoning_preference = {**expected, 'effort': 'high'}

    result = (await clients['admin'].get(PATH)).json()
    assert result['assistant'] == expected and result['report'] == 'follow'
    assert result['asr'] == stored['asr'] and result['image'] == stored['image']
    reasoning = (await clients['employee'].get('/api/v1/assistant/reasoning-settings')).json()
    assert reasoning['selected'] == {'effort': 'high'}
    for kind, purpose, effort in [('message', 'assistant', 'high'), ('report', 'report', 'low')]:
        job = SimpleNamespace(kind=kind, result={}, model_binding=None, config_attempt=0,
                              company_id=users['employee'].company_id, owner_id=users['employee'].id)
        async with sessions.begin() as db:
            binding = await bind_job(db, job, settings)
            config, _ = await resolve_bound(db, settings, job.company_id, binding, purpose)
        assert binding[purpose]['modelId'] == expected['modelId']
        assert config['parameters'] == {'reasoning_effort': effort}
        if purpose == 'assistant':
            assert binding['asr']['modelId'] == 'audio' and binding['image']['modelId'] == 'image'

    # A stale client cannot restore a separate report route or its overrides.
    updated = await clients['admin'].put(PATH, json={'expectedRevision': 3, 'report': stored['report']})
    assert updated.status_code == 200, updated.text
    assert updated.json()['assistant'] == expected and updated.json()['report'] == 'follow'
    # Explicitly clearing text must not revive the former report-only assignment.
    cleared = await clients['admin'].put(PATH, json={'expectedRevision': 4, 'assistant': None, 'report': stored['report']})
    assert cleared.status_code == 200, cleared.text
    result = (await clients['admin'].get(PATH)).json()
    assert result['assistant'] is None and result['report'] == 'follow'
    assert result['asr'] == stored['asr'] and result['image'] == stored['image']
    async with sessions() as db:
        row = await db.get(ModelRouting, users['admin'].company_id)
        assert row.choices['assistant'] is None and row.choices['report'] == 'follow'


@pytest.mark.parametrize('action', ['edit', 'delete'])
async def test_retired_report_route_does_not_block_service_management(setup, action):
    _, sessions, users, clients = setup
    text_service = await create(clients['admin'])
    retired = await create(clients['admin'], payload(name='旧报告服务'))
    async with sessions.begin() as db:
        db.add(ModelRouting(company_id=users['admin'].company_id, revision=1, choices={
            'assistant': {'serviceId': text_service['id'], 'modelId': 'chat'},
            'report': {'serviceId': retired['id'], 'modelId': 'chat'},
        }))
    path = '/api/v1/settings/model-services/'
    if action == 'edit':
        changed = {**payload(), 'apiKey': '', 'expectedRevision': 1, 'models': []}
        response = await clients['admin'].patch(path + retired['id'], json=changed)
    else:
        response = await clients['admin'].request('DELETE', path + retired['id'], json={'expectedRevision': 1})
    assert response.status_code == 200, response.text
    protected = await clients['admin'].request('DELETE', path + text_service['id'], json={'expectedRevision': 1})
    assert protected.status_code == 409 and '文字模型' in protected.text
    result = (await clients['admin'].get(PATH)).json()
    assert result['assistant']['serviceId'] == text_service['id'] and result['report'] == 'follow'
