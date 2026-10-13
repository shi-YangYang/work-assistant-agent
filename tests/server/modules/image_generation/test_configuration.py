from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.modules.model_services.bindings import bind_job, resolve_bound
from app.modules.model_services.models import ModelServiceRevision
from app.modules.model_services.schemas import ServiceModel
from app.integrations.models.transport import ProviderError
from app.tasks.models import Job
from _support.http.model_services import create, payload
from _support.agent.business_actions import runtime

pytestmark = pytest.mark.asyncio


def image_payload():
    value = payload(url='https://dashscope.aliyuncs.com/api/v1')
    value['models'].append({'id': 'image', 'model': 'wan2.7-image', 'protocol': 'dashscope-image'})
    return value


async def test_routing_capabilities_old_client_omission_and_frozen_binding(setup):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'], image_payload())
    choice = {'serviceId': saved['id'], 'modelId': 'image'}
    for purpose in ('assistant', 'asr'):
        assert (await clients['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision': 0, purpose: choice})).status_code == 422
    response = await clients['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision': 0, 'image': choice})
    assert response.status_code == 200 and response.json()['image'] == choice
    old = await clients['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision': 1, 'assistant': None, 'report': choice, 'asr': None})
    assert old.status_code == 200 and old.json()['image'] == choice
    assert old.json()['report'] == 'follow' and old.json()['assistant'] is None
    context, _ = await runtime(setup, '画一只鸟')
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        binding = await bind_job(db, job, settings)
    updated = await clients['admin'].patch('/api/v1/settings/model-services/' + saved['id'], json={**image_payload(), 'apiKey': 'different-controlled-key', 'expectedRevision': 1})
    assert updated.status_code == 200
    async with sessions() as db:
        config, key = await resolve_bound(db, settings, context.company_id, binding, 'image')
        assert key == image_payload()['apiKey'] and config['parameters'] == {} and config['streaming'] is False
        with pytest.raises(ProviderError, match='尚未配置'):
            await resolve_bound(db, settings, context.company_id, {'assistant': None}, 'image')
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision': 2, 'image': None})).json()['image'] is None


async def test_image_model_invalid_options_and_wrong_models_rejected(setup):
    clients = setup[3]
    for patch in ({'model': 'custom-image'}, {'language': 'zh'}, {'contextWindow': 1000}, {'parameters': {'enable_thinking': False}}):
        value = image_payload()
        value['models'][-1].update(patch)
        assert (await clients['admin'].post('/api/v1/settings/model-services', json=value)).status_code == 422
    assert (await clients['employee'].post('/api/v1/settings/model-services', json=image_payload())).status_code == 403


async def test_image_probe_explicit_one_call_checks_png_and_releases_connection(setup, monkeypatch):
    from app.integrations.models.images import wan, results
    import io
    from PIL import Image
    settings, sessions, users, clients = setup
    png = io.BytesIO()
    Image.new('RGB', (768, 768)).save(png, format='PNG')
    value = image_payload()
    submit = AsyncMock(return_value=('task-test', 'request-test'))
    query = AsyncMock(return_value={'output': {'task_status': 'SUCCEEDED', 'choices': [{'message': {'content': [{'image': 'https://image.example/a.png'}]}}]}})
    monkeypatch.setattr(wan, 'submit', submit)
    monkeypatch.setattr(wan, 'query', query)
    monkeypatch.setattr(results, 'download', AsyncMock(return_value=(png.getvalue(), results.metadata(png.getvalue()))))
    saved = await create(clients['admin'], value)
    assert submit.await_count == 0
    response = await clients['admin'].post('/api/v1/settings/model-services/test-image', json={**value, 'modelId': 'image', 'purpose': 'image', 'draftVersion': 'controlled-1'})
    assert response.status_code == 200, response.text
    assert response.json()['checks'][0]['state'] == 'passed'
    assert '768 × 768' in response.json()['checks'][0]['message']
    assert submit.await_count == 1 and response.json()['usage'] is None
    assert (await clients['admin'].post('/api/v1/settings/model-services/test-image', json={**value, 'modelId': 'image', 'purpose': 'asr', 'draftVersion': 'controlled-1'})).status_code == 422
