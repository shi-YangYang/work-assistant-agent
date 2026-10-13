"""Token Plan synchronous receipts use the same private delivery and fencing."""
import asyncio
import json
from copy import copy, deepcopy
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import event, func, select
from app.integrations.models.images import wan
from app.integrations.models.transport import ProviderError
from app.modules.deliverables.models import DeliverableRevision
from app.modules.executions.files import file_path
from app.modules.image_generation import service
from app.modules.image_generation.models import ImageGeneration
from app.modules.model_services.models import ModelUsage
from app.tasks.context import LostLease
from app.tasks.models import Job
from test_operations import configured, provider

pytestmark = pytest.mark.asyncio
TOKEN_PLAN = 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'


@pytest.fixture
def synchronous(provider, monkeypatch):
    response = deepcopy(provider.query.return_value)
    response['output'].pop('task_status')
    response['request_id'] = 'sync-request'
    provider.sync = AsyncMock(return_value=response)
    monkeypatch.setattr(wan, 'generate_sync', provider.sync)
    return provider


async def operation(setup, context):
    async with setup[1]() as db:
        return await db.scalar(select(ImageGeneration).where(ImageGeneration.job_id == context.job_id))


async def test_sync_duplicate_delivery_and_usage_preserve_private_receipt(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    first = await service.generate(context, prompt='画一只鸟')
    assert first['state'] == 'succeeded', first
    assert await service.generate(context, prompt='画一只鸟', operation=2) == first
    assert await service.generate(context, prompt='画一只鸟', width=2048, height=2048) == first
    row = await operation(setup, context)
    assert row.task_id is None and row.request_id == 'sync-request'
    assert row.provider_result == synchronous.sync.return_value
    assert 'https://image.example' not in json.dumps(first)
    assert synchronous.sync.await_count == 1 and synchronous.submit.await_count == synchronous.query.await_count == 0
    async with setup[1]() as db:
        usage = await db.get(ModelUsage, row.usage_id)
        assert usage.status == 'succeeded' and usage.actual_input_tokens == 9
    response = await setup[3]['employee'].get(first['delivery']['files'][0]['url'])
    assert response.status_code == 200 and response.content == synchronous.data


async def test_sync_download_publication_and_missing_cache_resume_without_post(setup, synchronous, monkeypatch):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    synchronous.download.side_effect = ProviderError('image_download', '暂时无法下载')
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
    synchronous.download.side_effect = None
    with monkeypatch.context() as patch:
        patch.setattr(service, 'publish', AsyncMock(side_effect=RuntimeError('controlled publication failure')))
        assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
    row = await operation(setup, context)
    file_path(context.settings, row.files[0]['storageKey']).unlink()
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'succeeded'
    assert synchronous.sync.await_count == 1 and synchronous.query.await_count == 0
    assert synchronous.download.await_count == 3


async def test_sync_unknown_response_blocks_same_and_changed_requests(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    synchronous.sync.side_effect = ProviderError('timeout', '受控超时')
    first = await service.generate(context, prompt='画一只鸟')
    assert first['state'] == 'unknown'
    assert await service.generate(context, prompt='画一只鸟') == first
    assert (await service.generate(context, prompt='画另一只鸟', operation=2))['state'] == 'unknown'
    assert synchronous.sync.await_count == 1 and synchronous.download.await_count == 0


async def test_sync_receipt_commit_failure_is_recovered_without_regeneration(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    interrupted = False
    def fail_once(mapper, connection, target):
        nonlocal interrupted
        if target.provider_result and target.state == 'downloading' and not interrupted:
            interrupted = True
            raise RuntimeError('controlled first receipt commit failure')
    event.listen(ImageGeneration, 'before_update', fail_once)
    try:
        assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
        assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'succeeded'
    finally:
        event.remove(ImageGeneration, 'before_update', fail_once)
    assert synchronous.sync.await_count == 1 and synchronous.query.await_count == 0


async def test_sync_late_receipt_after_lease_change_resumes_without_reposting(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args):
        assert setup[1].kw['bind'].pool.checkedout() == 0
        entered.set()
        await release.wait()
        return synchronous.sync.return_value
    synchronous.sync.side_effect = delayed
    pending = asyncio.create_task(service.generate(context, prompt='画一只鸟'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        duplicate = await service.generate(context, prompt='画一只鸟')
        assert duplicate['state'] == 'running'
        recovered = copy(context)
        async with setup[1].begin() as db:
            job = await db.get(Job, context.job_id)
            job.fence += 1
            recovered.fence = job.fence
        assert (await service.generate(recovered, prompt='画一只鸟'))['state'] == 'unknown'
        release.set()
        with pytest.raises(LostLease):
            await pending
        row = await operation(setup, context)
        assert row.provider_result and row.task_id is None
        assert (await service.generate(recovered, prompt='画一只鸟'))['state'] == 'succeeded'
        assert synchronous.sync.await_count == 1
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_sync_cancel_during_generation_stores_facts_but_cannot_publish(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    async def cancel(*args):
        async with setup[1].begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.fence = 'cancelled', job.fence + 1
        return synchronous.sync.return_value
    synchronous.sync.side_effect = cancel
    with pytest.raises(LostLease):
        await service.generate(context, prompt='画一只鸟')
    row = await operation(setup, context)
    assert row.provider_result and row.task_id is None
    assert synchronous.sync.await_count == 1 and synchronous.download.await_count == 0
    async with setup[1]() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision).where(DeliverableRevision.owner_id == context.owner_id)) == 0


async def test_sync_empty_result_never_resubmitted(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    synchronous.sync.return_value = {'output': {'choices': []}, 'request_id': 'empty-request', 'usage': {}}
    first = await service.generate(context, prompt='画一只鸟')
    assert first['state'] == 'failed' and '未返回可用图片' in first['message']
    assert await service.generate(context, prompt='画一只鸟') == first
    assert synchronous.sync.await_count == 1


async def test_sync_expired_receipt_result_is_terminal_without_new_generation(setup, synchronous):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    synchronous.download.side_effect = ProviderError('image_download', '受控临时下载失败')
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
    synchronous.download.side_effect = ProviderError('image_expired', '原图片结果已过期或不可用，无法恢复；没有重新生成', 410)
    expired = await service.generate(context, prompt='画一只鸟')
    assert expired['state'] == 'failed' and '没有重新生成' in expired['message']
    assert await service.generate(context, prompt='画一只鸟') == expired
    assert synchronous.sync.await_count == 1 and synchronous.download.await_count == 2 and synchronous.query.await_count == 0


async def test_sync_probe_uses_saved_token_plan_credentials_without_async_calls(setup, synchronous):
    from _support.http.model_services import payload, create
    value = payload(url=TOKEN_PLAN)
    value['models'] = [{'id': 'image', 'model': 'wan2.7-image', 'protocol': 'dashscope-image'}]
    saved = await create(setup[3]['admin'], value)
    response = await setup[3]['admin'].post('/api/v1/settings/model-services/test-image', json={**value, 'apiKey': '', 'serviceId': saved['id'], 'expectedRevision': 1, 'modelId': 'image', 'purpose': 'image', 'draftVersion': 'sync-probe'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['checks'][0]['state'] == 'passed' and result['usage']['output_tokens'] == 11
    assert result['providerRequestId'] == 'sync-request' and 'https://image.example' not in response.text
    assert synchronous.sync.await_count == 1 and synchronous.submit.await_count == synchronous.query.await_count == 0
    assert synchronous.sync.call_args.args[2] == value['apiKey']
