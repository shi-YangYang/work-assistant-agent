import asyncio
import io
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from sqlalchemy import select, func
from app.db.base import now
from app.integrations.models.images import results, wan
from app.integrations.models.transport import ProviderError
from app.modules.image_generation import service
from app.modules.image_generation.models import ImageGeneration
from app.modules.deliverables.models import DeliverableRevision
from app.modules.model_services.bindings import bind_job
from app.modules.model_services.models import ModelUsage, ModelService
from app.tasks.models import Job
from app.tasks.context import LostLease
from _support.agent.business_actions import runtime, finish
from _support.http.model_services import create, payload

pytestmark = pytest.mark.asyncio


@pytest.fixture
def provider(monkeypatch):
    stream = io.BytesIO()
    Image.new('RGB', (1000, 800), 'blue').save(stream, format='PNG')
    data = stream.getvalue()
    submit = AsyncMock(return_value=('task-1', 'req-1'))
    query = AsyncMock(return_value={'output': {'task_status': 'SUCCEEDED', 'choices': [{'message': {'content': [{'image': 'https://image.example/1.png'}]}}]}, 'usage': {'input_tokens': 9, 'output_tokens': 11}})
    download = AsyncMock(return_value=(data, results.metadata(data)))
    monkeypatch.setattr(wan, 'submit', submit)
    monkeypatch.setattr(wan, 'query', query)
    monkeypatch.setattr(results, 'download', download)
    return SimpleNamespace(submit=submit, query=query, download=download, data=data)


async def configured(setup, who='employee', base_url='https://dashscope.aliyuncs.com/api/v1'):
    settings, sessions, users, clients = setup
    body = payload(url=base_url)
    body['models'] = [{'id': 'image', 'model': 'wan2.7-image', 'protocol': 'dashscope-image'}]
    saved = await create(clients['admin'], body)
    current = (await clients['admin'].get('/api/v1/settings/model-routing')).json()
    response = await clients['admin'].put('/api/v1/settings/model-routing', json={'expectedRevision': current['revision'], 'image': {'serviceId': saved['id'], 'modelId': 'image'}})
    assert response.status_code == 200, response.text
    context, sent = await runtime(setup, '请画一只鸟', who=who)
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        context.model_binding = await bind_job(db, job, settings)
    return context, sent, saved


async def test_private_file_dimensions_duplicate_and_new_message(setup, provider):
    context, sent, _ = await configured(setup)
    first = await service.generate(context, prompt='画一只鸟')
    assert first['state'] == 'succeeded', first
    file = first['delivery']['files'][0]
    assert (file['width'], file['height']) == (1000, 800)
    assert (await setup[3]['employee'].get(file['url'])).content == provider.data
    for who in ('admin', 'peer', 'outsider'):
        assert (await setup[3][who].get(file['url'])).status_code == 404
    for args in ({}, {'operation': 2, 'resolution': '2K'}, {'operation': 3, 'width': 2048, 'height': 2048}):
        assert await service.generate(context, prompt='画一只鸟', **args) == first
    assert provider.submit.await_count == 1
    assert (await service.generate(context, prompt='画一只猫'))['state'] == 'conflict'
    message = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['deliverables'][0]['files'][0] == file
    await finish(context)
    context, _, _ = await configured(setup)
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'succeeded'
    assert provider.submit.await_count == 2


async def test_concurrent_claim_mixed_deliverable_slot_and_usage(setup, provider):
    from app.agent.tools.resources.deliverables import save_deliverable
    context, _, _ = await configured(setup)
    await save_deliverable.coroutine(title='已有文稿', body='原文', runtime=SimpleNamespace(context=context), step=1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def slow(*args):
        entered.set()
        await release.wait()
        return 'task-1', 'req-1'
    provider.submit.side_effect = slow
    task = asyncio.create_task(service.generate(context, prompt='画一只鸟'))
    await entered.wait()
    duplicate = await asyncio.wait_for(service.generate(context, prompt='画一只鸟', operation=2), 3)
    assert duplicate['state'] == 'running'
    release.set()
    result = await task
    assert result['state'] == 'succeeded' and provider.submit.await_count == 1
    async with setup[1]() as db:
        records = (await db.scalars(select(DeliverableRevision).where(DeliverableRevision.message_id == (await db.get(Job, context.job_id)).target_id))).all()
        assert {record.step for record in records} == {1, 2}
        usage = await db.scalar(select(ModelUsage).where(ModelUsage.job_id == context.job_id))
        assert usage.kind == 'image' and usage.status == 'succeeded' and usage.actual_output_tokens == 11


async def test_unknown_submit_blocks_parameter_drift_and_future_operations(setup, provider):
    context, _, _ = await configured(setup)
    provider.submit.side_effect = ProviderError('timeout', '连接中断')
    first = await service.generate(context, prompt='画一只鸟')
    assert first['state'] == 'unknown'
    assert await service.generate(context, prompt='画一只鸟') == first
    assert (await service.generate(context, prompt='画鸟，请加蓝色', operation=2))['state'] == 'unknown'
    assert provider.submit.await_count == 1 and provider.query.await_count == 0


async def test_known_task_download_and_publication_recover_without_regeneration(setup, provider, monkeypatch):
    context, _, _ = await configured(setup)
    provider.download.side_effect = ProviderError('image_download', '暂时无法下载')
    failed = await service.generate(context, prompt='画一只鸟')
    assert failed['state'] == 'retryable'
    provider.download.side_effect = None
    original = service.publish
    async def broken(*args):
        raise RuntimeError('controlled local publication failure')
    monkeypatch.setattr(service, 'publish', broken)
    second = await service.generate(context, prompt='画一只鸟')
    assert second['state'] == 'retryable'
    downloaded = provider.download.await_count
    monkeypatch.setattr(service, 'publish', original)
    result = await service.generate(context, prompt='画一只鸟')
    assert result['state'] == 'succeeded' and provider.submit.await_count == 1
    assert provider.download.await_count == downloaded


async def test_receipt_commit_failure_retains_task_id_and_never_submits_again(setup, provider):
    from sqlalchemy import event
    context, _, _ = await configured(setup)
    interrupted = False
    def fail_receipt_once(mapper, connection, target):
        nonlocal interrupted
        if target.task_id and target.state == 'polling' and not interrupted:
            interrupted = True
            raise RuntimeError('controlled receipt commit failure')
    event.listen(ImageGeneration, 'before_update', fail_receipt_once)
    try:
        assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
        assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'succeeded'
    finally:
        event.remove(ImageGeneration, 'before_update', fail_receipt_once)
    assert provider.submit.await_count == 1 and provider.query.await_count == 1


@pytest.mark.parametrize('point', ['query', 'download'])
async def test_cancel_and_revoke_never_publish_late_results(setup, provider, point):
    context, _, saved = await configured(setup)
    original = provider.query.return_value if point == 'query' else provider.download.return_value
    async def cancel(*args):
        async with setup[1].begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.fence = 'cancelled', job.fence + 1
        return original
    getattr(provider, point).side_effect = cancel
    with pytest.raises(LostLease):
        await service.generate(context, prompt='画一只鸟')
    async with setup[1]() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision).where(DeliverableRevision.owner_id == context.owner_id)) == 0


async def test_service_revocation_after_generation_cannot_publish(setup, provider):
    context, _, saved = await configured(setup)
    async def revoke(*args):
        async with setup[1].begin() as db:
            (await db.get(ModelService, saved['id'])).revoked = True
        return provider.download.return_value
    provider.download.side_effect = revoke
    assert (await service.generate(context, prompt='画一只鸟'))['state'] != 'succeeded'
    async with setup[1]() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision).where(DeliverableRevision.owner_id == context.owner_id)) == 0


async def test_recovered_worker_uses_known_task_and_rejects_unknown_window(setup, provider):
    context, _, _ = await configured(setup)
    row, _ = await service.claim(context, '画一只鸟', '图片', 1, None)
    async with setup[1].begin() as db:
        saved = await db.get(ImageGeneration, row.id)
        saved.state, saved.task_id = 'polling', 'known-task'
        job = await db.get(Job, context.job_id)
        job.fence += 1
        context.fence = job.fence
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'succeeded'
    assert provider.submit.await_count == 0
    assert provider.query.call_args.args[-1] == 'known-task'
    await finish(context)
    context, _, _ = await configured(setup)
    await service.claim(context, '画一只鸟', '图片', 1, None)
    async with setup[1].begin() as db:
        job = await db.get(Job, context.job_id)
        job.fence += 1
        context.fence = job.fence
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'unknown'
    assert provider.submit.await_count == 0


@pytest.mark.parametrize('network_failure', [False, True])
async def test_partial_results_keep_good_png_and_never_replay(setup, provider, network_failure):
    import httpx
    context, _, _ = await configured(setup)
    provider.query.return_value['output']['choices'][0]['message']['content'].append({'image': 'https://image.example/2.png'})
    provider.download.side_effect = [provider.download.return_value, httpx.ReadTimeout('controlled') if network_failure else ProviderError('image_format', '不是图片')]
    result = await service.generate(context, prompt='画一只鸟')
    assert result['state'] == 'succeeded' and result['imageCount'] == 1 and '部分' in result['message']
    assert await service.generate(context, prompt='画一只鸟') == result
    assert provider.submit.await_count == 1


async def test_unconfigured_and_invalid_size_never_submit(setup, provider):
    context, _ = await runtime(setup, '画图')
    with pytest.raises(ProviderError, match='尚未配置'):
        await service.generate(context, prompt='画图')
    context, _, _ = await configured(setup, who='peer')
    with pytest.raises(ProviderError, match='不支持 4K'):
        await service.generate(context, prompt='画图', resolution='4K')
    assert provider.submit.await_count == 0


async def test_late_task_id_after_lease_recovery_can_resume_query(setup, provider):
    context, _, _ = await configured(setup)
    row, _ = await service.claim(context, '画一只鸟', '图片', 1, None)
    async with setup[1].begin() as db:
        job = await db.get(Job, context.job_id)
        job.fence += 1
        context.fence = job.fence
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'unknown'
    async with setup[1].begin() as db:
        (await db.get(ImageGeneration, row.id)).task_id = 'late-task'
        usage = await db.get(ModelUsage, row.usage_id)
        usage.status, usage.started_at = 'unknown', now() - timedelta(seconds=10)
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'succeeded'
    assert provider.submit.await_count == 0 and provider.query.call_args.args[-1] == 'late-task'
    async with setup[1]() as db:
        usage = await db.get(ModelUsage, row.usage_id)
        assert usage.status == 'succeeded' and usage.actual_output_tokens == 11 and usage.elapsed_ms >= 10000


async def test_unpublished_files_survive_cleanup_then_deleted_conversation_is_cleaned(setup, provider, monkeypatch):
    import os, time
    from app.modules.executions.cleanup import clean_files
    from app.modules.executions.files import file_path
    from app.modules.conversations.models import Conversation
    context, sent, _ = await configured(setup)
    async def broken(*args):
        raise RuntimeError('controlled publication failure')
    monkeypatch.setattr(service, 'publish', broken)
    assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
    async with setup[1].begin() as db:
        row = await db.scalar(select(ImageGeneration).where(ImageGeneration.job_id == context.job_id))
        path = file_path(context.settings, row.files[0]['storageKey'])
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        await clean_files(db, context.settings)
        assert path.exists()
        (await db.get(Conversation, sent['conversationId'])).deleted = True
    async with setup[1].begin() as db:
        await clean_files(db, context.settings)
    assert not path.exists()


async def unpublished_file(setup, monkeypatch):
    from app.modules.executions.files import file_path
    context, _, _ = await configured(setup)
    async def broken(*args):
        raise RuntimeError('controlled publication failure')
    with monkeypatch.context() as patch:
        patch.setattr(service, 'publish', broken)
        assert (await service.generate(context, prompt='画一只鸟'))['state'] == 'retryable'
    async with setup[1]() as db:
        row = await db.scalar(select(ImageGeneration).where(ImageGeneration.job_id == context.job_id))
        return context, row.id, file_path(context.settings, row.files[0]['storageKey'])


async def expire_cache(setup, identifier, path):
    import os, time
    async with setup[1].begin() as db:
        (await db.get(ImageGeneration, identifier)).updated_at = now() - timedelta(hours=25)
    os.utime(path, (time.time() - 25 * 3600, time.time() - 25 * 3600))


@pytest.mark.parametrize('damage', ['missing', 'content', 'size', 'symlink', 'cleanup'])
async def test_invalid_cached_file_recovers_original_task_without_reposting(setup, provider, monkeypatch, damage):
    from app.modules.executions.cleanup import clean_files
    context, identifier, path = await unpublished_file(setup, monkeypatch)
    if damage == 'missing':
        path.unlink()
    elif damage == 'content':
        path.write_bytes(b'x' * len(provider.data))
    elif damage == 'size':
        path.write_bytes(provider.data[:100])
    elif damage == 'symlink':
        target = path.with_suffix('.reference')
        path.rename(target)
        path.symlink_to(target)
    else:
        await expire_cache(setup, identifier, path)
        async with setup[1].begin() as db:
            await clean_files(db, context.settings)
        assert not path.exists()
    result = await service.generate(context, prompt='画一只鸟')
    assert result['state'] == 'succeeded', result
    assert provider.submit.await_count == 1 and provider.query.await_count == 2 and provider.download.await_count == 2
    assert provider.query.call_args.args[-1] == 'task-1'
    assert not path.is_symlink()
    response = await setup[3]['employee'].get(result['delivery']['files'][0]['url'])
    assert response.status_code == 200 and response.content == provider.data


@pytest.mark.parametrize('expired', ['task', 'result'])
async def test_expired_original_cannot_publish_missing_file_or_generate_again(setup, provider, monkeypatch, expired):
    from app.modules.executions.cleanup import clean_files
    context, identifier, path = await unpublished_file(setup, monkeypatch)
    await expire_cache(setup, identifier, path)
    async with setup[1].begin() as db:
        await clean_files(db, context.settings)
    assert not path.exists()
    if expired == 'task':
        provider.query.side_effect = ProviderError('protocol', 'task missing', 404)
    else:
        provider.download.side_effect = ProviderError('image_expired', '原图片结果已过期或不可用，无法恢复；没有重新生成', 410)
    result = await service.generate(context, prompt='画一只鸟')
    assert result['state'] == 'failed' and '没有重新生成' in result['message'] and 'delivery' not in result
    queries = provider.query.await_count
    assert await service.generate(context, prompt='画一只鸟') == result
    assert provider.submit.await_count == 1 and provider.query.await_count == queries
    async with setup[1]() as db:
        assert not (await db.get(ImageGeneration, identifier)).files
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision).where(DeliverableRevision.owner_id == context.owner_id)) == 0


async def test_cleanup_between_cache_verification_and_publish_is_rechecked(setup, provider, monkeypatch):
    from app.modules.executions import cleanup
    context, identifier, path = await unpublished_file(setup, monkeypatch)
    await expire_cache(setup, identifier, path)
    snapshot_taken, files_checked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    original_check = service.checked_files
    def checked(*args):
        value = original_check(*args)
        loop.call_soon_threadsafe(files_checked.set)
        return value
    monkeypatch.setattr(service, 'checked_files', checked)
    async def cleaning():
        async with setup[1].begin() as db:
            execute = db.execute
            async def paused_snapshot(statement, *args, **kwargs):
                value = await execute(statement, *args, **kwargs)
                if 'company_image_generation' in str(statement):
                    snapshot_taken.set()
                    await release.wait()
                return value
            monkeypatch.setattr(db, 'execute', paused_snapshot)
            await cleanup.clean_files(db, context.settings)
    cleaning_task = asyncio.create_task(cleaning())
    generation_task = None
    try:
        await asyncio.wait_for(snapshot_taken.wait(), 5)
        generation_task = asyncio.create_task(service.generate(context, prompt='画一只鸟'))
        await asyncio.wait_for(files_checked.wait(), 5)
        assert not generation_task.done()
        release.set()
        await asyncio.wait_for(cleaning_task, 5)
        result = await asyncio.wait_for(generation_task, 5)
    finally:
        release.set()
        for task in (cleaning_task, generation_task):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert result['state'] == 'succeeded' and provider.submit.await_count == 1 and provider.download.await_count == 2
    response = await setup[3]['employee'].get(result['delivery']['files'][0]['url'])
    assert response.status_code == 200 and response.content == provider.data


@pytest.mark.parametrize('final_failure', [False, True])
@pytest.mark.parametrize('synchronous', [False, True])
@pytest.mark.parametrize('batch', [False, True])
async def test_agent_lazy_generation_duplicate_calls_persists_before_final_text(setup, provider, monkeypatch, final_failure, synchronous, batch):
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from _support.agent.response_delivery import DeliveryModel
    from app.tasks.processing.handlers import process_job
    class PictureModel(DeliveryModel):
        async def _agenerate(self, messages, **kwargs):
            self.calls += 1
            tools = [item['function']['name'] for item in kwargs.get('tools', [])]
            previous = [message for message in messages if isinstance(message, ToolMessage)]
            if not any(message.name == 'load_tools' for message in previous):
                assert tools == ['load_tools']
                answer = AIMessage(content='', tool_calls=[{'id': 'load-images', 'name': 'load_tools', 'args': {'groups': ['images']}}])
            else:
                assert 'generate_image' in tools and 'run_python' not in tools
                count = len([message for message in previous if message.name == 'generate_image'])
                if count < (1 if batch else 2):
                    answer = AIMessage(content='', tool_calls=[{'id': f'image-call-{count}', 'name': 'generate_image', 'args': {'prompt': '画一只鸟', 'operation': count + 1, **({'count': 4} if batch else {})}}])
                else:
                    # The image already exists before the final text is produced.
                    result = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
                    assert result['deliverables'][0]['files'][0]['width'] == 1000
                    if final_failure:
                        raise ProviderError('protocol', '受控最终文字失败', 400)
                    answer = AIMessage(content='<!--noria:{}-->\n图片已生成，可以下载。')
            return ChatResult(generations=[ChatGeneration(message=answer)])
    generate_sync = AsyncMock(return_value={**provider.query.return_value, 'request_id': 'agent-sync'})
    monkeypatch.setattr(wan, 'generate_sync', generate_sync)
    context, sent, _ = await configured(setup, base_url='https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1' if synchronous else 'https://dashscope.aliyuncs.com/api/v1')
    async with setup[1]() as db:
        job = await db.get(Job, context.job_id)
    fake = PictureModel(model='controlled-image-agent', api_key='no-network')
    async with AsyncPostgresSaver.from_conn_string(setup[0].checkpoint_url) as saver:
        await process_job(job, setup[1], setup[0], saver, model=fake)
    result = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['job']['state'] == ('failed' if final_failure else 'succeeded'), result
    expected_images = 4 if batch else 1
    assert len(result['deliverables']) == expected_images
    assert provider.submit.await_count == (0 if synchronous else expected_images)
    assert generate_sync.await_count == (expected_images if synchronous else 0)
    assert fake.calls == (3 if batch else 4)
    assert any(node['label'] == '生成图片' for node in result['job']['nodes'])


@pytest.mark.parametrize('failure', ['rate_limit', 'refusal', 'empty'])
async def test_rejection_and_empty_results_never_repost(setup, provider, failure):
    context, _, _ = await configured(setup)
    if failure == 'rate_limit':
        provider.submit.side_effect = ProviderError('rate_limit', '服务请求暂时受限，请稍后重试', 429)
    elif failure == 'refusal':
        provider.query.return_value = {'output': {'task_status': 'FAILED', 'code': 'DataInspectionFailed'}}
    else:
        provider.query.return_value = {'output': {'task_status': 'SUCCEEDED', 'choices': []}}
    first = await service.generate(context, prompt='画一只鸟')
    second = await service.generate(context, prompt='画一只鸟', operation=2)
    assert first['state'] in ('failed', 'retryable') and second['state'] == first['state']
    assert provider.submit.await_count == 1 and provider.download.await_count == 0
