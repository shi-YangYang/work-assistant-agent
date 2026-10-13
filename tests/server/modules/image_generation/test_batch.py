import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from langchain_core.messages import ToolMessage
from app.agent.runtime.tool_nodes import outcome
from app.agent.tools.resources.images import generate_image
from app.integrations.models.images import wan
from app.integrations.models.transport import ProviderError
from app.modules.image_generation.batch import generate_batch
from .test_operations import configured, provider

pytestmark = pytest.mark.asyncio
TOKEN_PLAN = 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'


@pytest.mark.parametrize('synchronous', [False, True])
async def test_four_variants_are_saved_sequentially_and_replayed_without_new_requests(setup, provider, monkeypatch, synchronous):
    context, sent, _ = await configured(setup, base_url=TOKEN_PLAN if synchronous else 'https://dashscope.aliyuncs.com/api/v1')
    started = []
    async def generate(*args):
        # Each finished image is already visible through the real message API
        # before the next provider request starts, without another model turn.
        message = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
        assert len(message['deliverables']) == len(started)
        feedback = (await setup[3]['employee'].get('/api/v1/jobs/' + context.job_id + '/feedback')).json()
        assert feedback['imageDeliveryCount'] == len(started)
        slots = feedback['imageGeneration']
        assert [slot['state'] for slot in slots] == ['ready'] * len(started) + ['generating'] + ['queued'] * (3 - len(started))
        assert slots == message['job']['imageGeneration']
        assert slots[len(started)]['width'] == slots[len(started)]['height'] == 2048
        assert all('prompt' not in slot and 'url' not in slot for slot in slots)
        started.append(args[3])
        return deepcopy(provider.query.return_value) if synchronous else (f'task-{len(started)}', 'request')
    if synchronous:
        monkeypatch.setattr(wan, 'generate_sync', AsyncMock(side_effect=generate))
    else:
        provider.submit.side_effect = generate
    result = json.loads(await generate_image.coroutine(runtime=SimpleNamespace(context=context), prompt='画一只猫', count=4))
    assert result['state'] == 'succeeded' and result['imageCount'] == 4
    assert len({row['operationId'] for row in result['results']}) == 4
    assert started == ['画一只猫'] * 4
    recovered = replace(context, image_generation_lock=asyncio.Lock())
    assert await generate_batch(recovered, prompt='画一只猫', count=4) == result
    assert len(started) == 4
    feedback = (await setup[3]['employee'].get('/api/v1/jobs/' + context.job_id + '/feedback')).json()
    assert feedback['imageDeliveryCount'] == 4
    assert [slot['deliverableId'] for slot in feedback['imageGeneration']] == [row['delivery']['id'] for row in result['results']]
    assert all(slot['state'] == 'ready' for slot in feedback['imageGeneration'])


async def test_distinct_batches_in_one_message_do_not_overlap(setup, provider, monkeypatch):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    first_started, release = asyncio.Event(), asyncio.Event()
    prompts = []
    async def generate(*args):
        prompts.append(args[3])
        if len(prompts) == 1:
            first_started.set()
            await release.wait()
        return deepcopy(provider.query.return_value)
    monkeypatch.setattr(wan, 'generate_sync', AsyncMock(side_effect=generate))
    tasks = [asyncio.create_task(generate_batch(context, prompts=['猫', '狗']))]
    try:
        await asyncio.wait_for(first_started.wait(), 3)
        tasks.append(asyncio.create_task(generate_batch(context, prompts=['鸟', '兔'], operation=3)))
        await asyncio.sleep(0)
        assert prompts == ['猫'] and not tasks[1].done()
        release.set()
        values = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert prompts == ['猫', '狗', '鸟', '兔']
    assert [value['imageCount'] for value in values] == [2, 2]


@pytest.mark.parametrize('args', [
    {'prompt': '猫', 'count': 5}, {'prompts': ['猫'] * 5},
    {'prompts': ['猫', '']}, {'prompt': '猫', 'count': 4, 'operation': 2},
    {'prompt': '猫', 'prompts': ['狗']}, {'prompts': ['猫'], 'count': 2},
    {'prompts': ['猫', '狗', '鸟', '兔'], 'count': 2},
    {'prompts': ['猫', '狗', '鸟', '兔'], 'count': 4, 'operation': 2},
])
async def test_invalid_batch_is_rejected_before_any_generation(setup, provider, args):
    context, _, _ = await configured(setup)
    with pytest.raises(ProviderError):
        await generate_batch(context, **args)
    provider.submit.assert_not_awaited()


async def test_partial_failure_keeps_successes_and_never_recreates_them(setup, provider, monkeypatch):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    response = provider.query.return_value
    generate = AsyncMock(side_effect=[response, ProviderError('protocol', '图片请求被拒绝', 400), response, response])
    monkeypatch.setattr(wan, 'generate_sync', generate)
    result = await generate_batch(context, prompts=['猫', '狗', '鸟', '兔'])
    assert result['state'] == 'partial' and result['imageCount'] == 3 and result['notExecutedCount'] == 0
    assert [row['state'] for row in result['results']] == ['succeeded', 'failed', 'succeeded', 'succeeded']
    assert await generate_batch(context, prompts=['猫', '狗', '鸟', '兔']) == result
    assert generate.await_count == 4
    feedback = (await setup[3]['employee'].get('/api/v1/jobs/' + context.job_id + '/feedback')).json()
    assert [slot['state'] for slot in feedback['imageGeneration']] == ['ready', 'failed', 'ready', 'ready']
    message = ToolMessage(name='generate_image', tool_call_id='images', content=json.dumps(result))
    assert outcome(message) == ('failed', '已生成 3/4 张，部分图片未完成')


async def test_unknown_request_stops_batch_without_resubmitting(setup, provider, monkeypatch):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    generate = AsyncMock(side_effect=[provider.query.return_value, ProviderError('timeout', '结果未知')])
    monkeypatch.setattr(wan, 'generate_sync', generate)
    result = await generate_batch(context, prompt='猫', count=4)
    assert result['state'] == 'unknown' and result['imageCount'] == 1 and result['notExecutedCount'] == 2
    assert await generate_batch(context, prompt='猫', count=4) == result
    assert generate.await_count == 2
    feedback = (await setup[3]['employee'].get('/api/v1/jobs/' + context.job_id + '/feedback')).json()
    assert [slot['state'] for slot in feedback['imageGeneration']] == ['ready', 'unknown', 'not_started', 'not_started']


async def test_batch_retry_resumes_download_and_generates_only_remaining_images(setup, provider, monkeypatch):
    context, _, _ = await configured(setup, base_url=TOKEN_PLAN)
    generate = AsyncMock(return_value=provider.query.return_value)
    monkeypatch.setattr(wan, 'generate_sync', generate)
    download = provider.download.return_value
    provider.download.side_effect = [download, ProviderError('image_download', '下载暂时失败')]
    first = await generate_batch(context, prompt='猫', count=4)
    assert first['state'] == 'retryable' and first['imageCount'] == 1 and first['notExecutedCount'] == 2
    provider.download.side_effect = None
    recovered = replace(context, image_generation_lock=asyncio.Lock())
    result = await generate_batch(recovered, prompt='猫', count=4)
    assert result['state'] == 'succeeded' and result['imageCount'] == 4
    assert generate.await_count == 4
    assert result['results'][0] == first['results'][0]


@pytest.mark.parametrize('state, expected', [('cancelled', ['ready', 'cancelled', 'cancelled']), ('failed', ['ready', 'interrupted', 'not_started']), ('succeeded', ['ready', 'interrupted', 'not_started'])])
async def test_terminal_image_feedback_never_keeps_pending_slots_animating(state, expected):
    from app.tasks.feedback.image_feedback import dto
    slots = [{'operation': number, 'state': value} for number, value in enumerate(['ready', 'generating', 'queued'], 1)]
    job = SimpleNamespace(state=state, result={'imageGeneration': slots})
    assert [slot['state'] for slot in dto(job)] == expected
    assert [slot['state'] for slot in slots] == ['ready', 'generating', 'queued']


async def test_original_split_then_batch_retry_reuses_first_image_without_duplicates(setup, provider):
    context, sent, _ = await configured(setup)
    prompts = ['3D猫和老鼠打翻牛奶', '3D猫和老鼠追逐', '3D猫和老鼠和解', '3D猫和老鼠分享晚餐']
    first = await generate_batch(context, prompt=prompts[0])
    assert first['state'] == 'succeeded'
    for prompt in prompts[1:]:
        assert (await generate_batch(context, prompt=prompt))['state'] == 'conflict'
    assert provider.submit.await_count == 1
    complete = await generate_batch(context, prompts=prompts)
    assert complete['state'] == 'succeeded' and complete['imageCount'] == 4
    assert complete['results'][0] == first
    assert len({row['operationId'] for row in complete['results']}) == 4
    assert provider.submit.await_count == 4
    message = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(message['deliverables']) == 4
    assert len({file['id'] for row in message['deliverables'] for file in row['files']}) == 4


async def test_original_high_count_and_prompt_list_trace_uses_the_same_four_receipts(setup, provider):
    context, sent, _ = await configured(setup)
    # Exact three calls from the frozen high-2 trace; the first two formerly
    # failed only because count=4 redundantly repeated the list length.
    arguments = {
        'prompts': [
            '3D卡通渲染风格，一只圆润的橘猫和一只小灰老鼠坐在木桌旁一起喝下午茶，桌上有茶壶和两只小茶杯，热气袅袅，暖黄色灯光，柔和景深，皮克斯动画质感，温馨可爱',
            '3D卡通渲染风格，一只小猫和一只小老鼠在厨房木地板上追逐一块黄色奶酪，奶酪在前方滚动，姿态夸张有动感，明亮阳光，皮克斯动画质感，活泼有趣',
            '3D卡通渲染风格，猫咪和小老鼠在客厅玩躲猫猫，猫咪从沙发后探出头找，小老鼠躲在绿植花盆后面偷笑，条纹地毯，柔和自然光，皮克斯动画质感，俏皮可爱',
            '3D卡通渲染风格，猫咪和小老鼠坐在野餐垫上分享一块草莓奶油蛋糕，两只各拿一把小叉子，蛋糕上有蜡烛和莓果装饰，草坪与蓝天背景，皮克斯动画质感，温暖甜蜜',
        ],
        'title': '3D猫和老鼠四格场景', 'count': 4,
    }
    first = json.loads(await generate_image.coroutine(runtime=SimpleNamespace(context=context), **arguments))
    assert first['state'] == 'succeeded' and first['imageCount'] == 4
    second = json.loads(await generate_image.coroutine(runtime=SimpleNamespace(context=context), **arguments, operation=1))
    arguments.pop('count')
    third = json.loads(await generate_image.coroutine(runtime=SimpleNamespace(context=context), **arguments, operation=1))
    assert second == third == first
    assert provider.submit.await_count == 4
    assert [call.args[3] for call in provider.submit.await_args_list] == arguments['prompts']
    message = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(message['deliverables']) == 4
    assert len({file['id'] for row in message['deliverables'] for file in row['files']}) == 4
