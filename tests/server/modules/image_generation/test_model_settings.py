"""Configurable image models retain immutable operations and provider contracts."""
import io
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select
from app.integrations.models.images import sizes, wan, results
from app.integrations.models.transport import ProviderError
from app.modules.model_services.schemas import ServiceModel
from app.modules.model_services.bindings import bind_job, resolve_bound
from app.modules.model_services.models import ModelServiceRevision
from app.modules.image_generation.models import ImageGeneration
from app.modules.image_generation import service
from app.tasks.models import Job
from _support.agent.business_actions import runtime
from _support.http.model_services import create, payload
from test_operations import provider


def custom_model(**patch):
    return {'id': 'image', 'model': 'future-image-v9', 'protocol': 'dashscope-image',
        'imageSettings': {'api': 'multimodal-sync', 'sizeMode': 'provider', 'sizes': [], 'defaultSize': None}, **patch}


def test_model_validation_and_profile_sizes():
    model = custom_model()
    assert ServiceModel(**model).model_dump()['imageSettings'] == model['imageSettings']
    with pytest.raises(ValidationError, match='自动接口'):
        ServiceModel(**{**model, 'imageSettings': None})
    with pytest.raises(ValidationError, match='只有图片'):
        ServiceModel(**{**model, 'protocol': 'chat'})
    for size in ('99999*99999', '0*1024', '1024x1024'):
        with pytest.raises(ValidationError):
            ServiceModel(**custom_model(imageSettings={'api': 'multimodal-sync', 'sizeMode': 'fixed', 'sizes': [size], 'defaultSize': size}))
    assert sizes.normalize(config=model) is None
    assert sizes.wire_size(model, None) is None
    assert sizes.normalize(config=model, width=512, height=512) == '512*512'
    for intent in ({'aspect':'16:9'}, {'resolution':'2K'}, {'width':99999, 'height':99999}):
        with pytest.raises(ProviderError):
            sizes.normalize(config=model, **intent)
    pro = {'model': 'wan2.7-image-pro'}
    assert sizes.wire_size(pro, sizes.normalize(config=pro, resolution='4K')) == '4096*4096'
    assert sizes.normalize(config=pro, aspect='16:9', resolution='4K') == '5376*3072'
    assert sizes.wire_size(pro, None) == '2048*2048'
    with pytest.raises(ProviderError, match='支持 1K、2K、4K'):
        sizes.normalize(config=pro, resolution='8K')
    assert sizes.wire_size({'model':'wan2.7-image', 'imageSettings': {'sizeMode':'provider'}}, None) is None


def test_fixed_sizes_keep_explicit_pixels_and_match_ratios_without_silent_replacement():
    model = custom_model(imageSettings={'api':'image-async', 'sizeMode':'fixed',
        'sizes':['1024*1024', '1536*1024', '1024*1536'], 'defaultSize':'1024*1024'})
    assert sizes.normalize(config=model) == '1024*1024'
    assert sizes.normalize(config=model, aspect='3:2') == '1536*1024'
    assert sizes.normalize(config=model, width=1024, height=1536) == '1024*1536'
    for intent in ({'aspect':'16:9'}, {'resolution':'4K'}, {'width':1024, 'height':1024, 'aspect':'3:2'}, {'width':512, 'height':512}):
        with pytest.raises(ProviderError):
            sizes.normalize(config=model, **intent)


def test_general_png_bounds_accept_pro_and_smaller_model_images():
    for width, height in ((512, 512), (4096, 4096), (5376, 3072)):
        stream = io.BytesIO()
        Image.new('RGB', (width, height)).save(stream, format='PNG')
        assert results.metadata(stream.getvalue())['width'] == width
    # Reject dimensions from the header before attempting a huge decompression.
    import struct, zlib
    stream = io.BytesIO()
    Image.new('RGB', (1, 1)).save(stream, format='PNG')
    data = bytearray(stream.getvalue())
    data[16:24] = struct.pack('>II', 32768, 1)
    data[29:33] = struct.pack('>I', zlib.crc32(data[12:29]) & 0xffffffff)
    with pytest.raises(ProviderError):
        results.metadata(bytes(data))


@pytest.mark.asyncio
@pytest.mark.parametrize('api', ['multimodal-sync', 'image-async'])
async def test_custom_gateway_protocol_omits_unknown_size_and_never_falls_back(monkeypatch, api):
    calls = []
    config = {'baseUrl':'https://image-gateway.example/compatible-mode/v1', **custom_model()}
    config['imageSettings']['api'] = api
    def handle(request):
        calls.append(request)
        body = json.loads(request.content)
        assert request.url.host == 'image-gateway.example'
        assert request.headers['authorization'] == 'Bearer controlled-key'
        assert body['model'] == 'future-image-v9' and body['parameters'] == {'n':1}
        assert ('x-dashscope-async' in request.headers) == (api == 'image-async')
        assert request.url.path.endswith('/multimodal-generation/generation' if api == 'multimodal-sync' else '/image-generation/generation')
        return httpx.Response(400, json={'code':'InvalidParameter'})
    monkeypatch.setattr(wan, 'client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with pytest.raises(ProviderError):
        await (wan.generate_sync if api == 'multimodal-sync' else wan.submit)(SimpleNamespace(model_allowed_origins=()), config, 'controlled-key', 'bird')
    assert len(calls) == 1
    config['imageSettings']['api'] = 'auto'
    with pytest.raises(ProviderError, match='自动匹配'):
        wan.endpoint(SimpleNamespace(model_allowed_origins=()), config)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_custom_model_save_probe_and_agent_recovery_use_frozen_configuration(setup, provider, monkeypatch):
    settings, sessions, users, clients = setup
    fixed = {'api':'multimodal-sync', 'sizeMode':'fixed', 'sizes':['1024*1024', '1536*1024'], 'defaultSize':'1024*1024'}
    value = {**payload(url='https://compatible-images.example/api/v1'), 'models':[custom_model(imageSettings=fixed)]}
    saved = await create(clients['admin'], value)
    assert saved['models'][0]['imageSettings'] == fixed
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision':0, 'image':{'serviceId':saved['id'], 'modelId':'image'}})).status_code == 200
    response = deepcopy(provider.query.return_value)
    response['output'].pop('task_status')
    sync = AsyncMock(return_value=response)
    monkeypatch.setattr(wan, 'generate_sync', sync)
    probed = await clients['admin'].post('/api/v1/settings/model-services/test-image', json={**value, 'modelId':'image', 'purpose':'image', 'draftVersion':'fixed-probe'})
    assert probed.status_code == 200 and probed.json()['checks'][0]['state'] == 'passed'
    assert sync.call_args.args[-1] == '1024*1024'
    context, _ = await runtime(setup, '请生成一张鸟的图片')
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        context.model_binding = await bind_job(db, job, settings)
    provider.download.side_effect = ProviderError('image_download', 'controlled download interruption')
    assert (await service.generate(context, prompt='bird', aspect='3:2'))['state'] == 'retryable'
    assert sync.call_args.args[-1] == '1536*1024'
    changed = {**value, 'expectedRevision':1, 'models':[custom_model(imageSettings={**fixed, 'api':'image-async', 'sizes':['2048*2048'], 'defaultSize':'2048*2048'})]}
    assert (await clients['admin'].patch('/api/v1/settings/model-services/'+saved['id'], json=changed)).status_code == 200
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        old_config, _ = await resolve_bound(db, settings, context.company_id, job.model_binding, 'image')
        assert old_config['imageSettings'] == fixed
        job.result = {**job.result, 'refreshModelBinding':True}
        context.model_binding = await bind_job(db, job, settings)
        new_config, _ = await resolve_bound(db, settings, context.company_id, job.model_binding, 'image')
        assert new_config['imageSettings']['api'] == 'image-async'
    provider.download.side_effect = None
    restored = await service.generate(context, prompt='bird', aspect='3:2')
    assert restored['state'] == 'succeeded'
    assert sync.await_count == 2 and provider.submit.await_count == provider.query.await_count == 0
    async with sessions() as db:
        row = await db.scalar(select(ImageGeneration).where(ImageGeneration.job_id == context.job_id))
        assert row.request['size'] == '1536*1024' and row.provider_result
    # A genuinely new operation uses the refreshed frozen job config.
    with pytest.raises(ProviderError, match='尺寸'):
        await service.generate(context, prompt='another bird', operation=2, aspect='3:2')
    assert sync.await_count == 2 and provider.submit.await_count == 0
