"""HTTP reads and explicit legacy configuration import on the isolated fixture."""
from dataclasses import replace
import pytest
from sqlalchemy import select

from app.modules.members.models import Member
from app.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
from app.security.secrets import decrypt
from test_model_services import SECRET, create, payload


pytestmark = pytest.mark.asyncio


async def test_model_service_list_returns_only_current_company_public_services(setup):
    _, sessions, users, clients = setup
    visible = await create(clients['admin'], payload(name='可见服务'))
    hidden = await create(clients['admin'], payload(name='内部服务'))
    removed = await create(clients['admin'], payload(name='已删除服务'))
    response = await clients['admin'].request('DELETE', '/api/v1/settings/model-services/' + removed['id'], json={'expectedRevision': 1})
    assert response.status_code == 200
    async with sessions.begin() as db:
        (await db.get(ModelService, hidden['id'])).internal = True
        (await db.get(Member, users['outsider'].id)).role = 'admin'
    other = await create(clients['outsider'], payload(name='其它公司的服务'))

    response = await clients['admin'].get('/api/v1/settings/model-services')
    assert response.status_code == 200, response.text
    assert response.json()['services'] == [visible]
    assert response.json()['routing']['source'] == 'environment'
    assert SECRET not in response.text and 'credential' not in response.text
    other_response = await clients['outsider'].get('/api/v1/settings/model-services')
    assert other_response.status_code == 200
    assert other_response.json()['services'] == [other]
    assert other_response.json()['routing']['source'] == 'database'
    for role in ('employee', 'peer'):
        assert (await clients[role].get('/api/v1/settings/model-services')).status_code == 403


async def test_model_service_detail_returns_current_revision_without_secret(setup):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    changed = await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json={**payload(name='更新后的服务'), 'apiKey': '', 'expectedRevision': 1})
    assert changed.status_code == 200
    path = '/api/v1/settings/model-services/' + saved['id']
    response = await clients['admin'].get(path)
    assert response.status_code == 200, response.text
    assert response.json() == changed.json()
    assert response.json()['revision'] == 2 and response.json()['hasKey'] is True
    async with sessions.begin() as db:
        (await db.get(Member, users['outsider'].id)).role = 'admin'
        revision = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id == saved['id'], ModelServiceRevision.revision == 2))
        assert decrypt(settings.model_key_file, revision.credential, users['admin'].company_id, saved['id'], 2) == SECRET
        assert revision.credential not in response.text
    assert SECRET not in response.text and 'credential' not in response.text
    assert (await clients['employee'].get(path)).status_code == 403
    assert (await clients['outsider'].get(path)).status_code == 404
    async with sessions.begin() as db:
        (await db.get(ModelService, saved['id'])).internal = True
    assert (await clients['admin'].get(path)).status_code == 404


async def test_environment_import_http_is_explicit_encrypted_and_once_per_company(setup, monkeypatch):
    settings, sessions, users, clients = setup
    configured = replace(settings, agent_base_url='https://example.com/v1', agent_key=SECRET, agent_model='legacy-chat', agent_options={'enable_thinking': False}, asr_base_url='https://example.com/v1', asr_key=SECRET, asr_model='legacy-asr')
    monkeypatch.setattr(clients['admin']._transport.app.state, 'settings', configured)
    company_id = users['admin'].company_id
    for _ in range(2):
        response = await clients['admin'].get('/api/v1/settings/model-services')
        assert response.status_code == 200
        assert response.json()['services'] == []
        assert response.json()['routing']['source'] == 'environment'
        assert SECRET not in response.text
    async with sessions() as db:
        assert await db.get(ModelRouting, company_id) is None
        assert not (await db.scalars(select(ModelService).where(ModelService.company_id == company_id))).all()
    path = '/api/v1/settings/model-services/import-environment'
    assert (await clients['employee'].post(path)).status_code == 403
    async with sessions.begin() as db:
        (await db.get(Member, users['outsider'].id)).role = 'admin'
    assert (await clients['outsider'].post(path)).status_code == 409
    response = await clients['admin'].post(path)
    assert response.status_code == 200, response.text
    routing = response.json()
    assert routing['source'] == 'database' and routing['revision'] == 1
    assert routing['report'] == 'follow' and routing['environment'] is None
    assert routing['assistant']['serviceId'] == routing['asr']['serviceId']
    assert routing['assistant']['modelId'] == 'assistant'
    assert routing['asr']['modelId'] == 'asr'
    assert SECRET not in response.text
    assert (await clients['admin'].post(path)).status_code == 409
    listing = await clients['admin'].get('/api/v1/settings/model-services')
    assert listing.status_code == 200 and listing.json()['routing'] == routing
    assert len(listing.json()['services']) == 1
    assert SECRET not in listing.text and 'credential' not in listing.text
    service_id = routing['assistant']['serviceId']
    async with sessions() as db:
        service = await db.get(ModelService, service_id)
        assert service.company_id == company_id and service.revision == 2
        assert {(item['id'], item['model'], item['protocol']) for item in service.models} == {('assistant', 'legacy-chat', 'chat'), ('asr', 'legacy-asr', 'qwen-asr')}
        assert all(item['streaming'] is False for item in service.models)
        assistant = next(item for item in service.models if item['id'] == 'assistant')
        assert assistant['presets'][0]['parameters'] == {'enable_thinking': False}
        revisions = (await db.scalars(select(ModelServiceRevision).where(ModelServiceRevision.service_id == service_id).order_by(ModelServiceRevision.revision))).all()
        assert [item.revision for item in revisions] == [1, 2]
        for item in revisions:
            assert SECRET not in item.credential
            assert decrypt(settings.model_key_file, item.credential, company_id, service_id, item.revision) == SECRET
        stored = await db.get(ModelRouting, company_id)
        assert stored.revision == 1 and stored.choices == {key: routing[key] for key in ('assistant', 'report', 'asr')}
        other_services = (await db.scalars(select(ModelService).where(ModelService.company_id == users['outsider'].company_id))).all()
        assert other_services == []
