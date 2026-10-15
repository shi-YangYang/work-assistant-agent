"""Usage errors retain their origin through streaming and the admin API."""
import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.core.errors import problem
from app.integrations.models.chat import chat
from app.integrations.models.transport import ProviderError
from app.modules.model_services.models import ModelUsage
from app.modules.model_services.usage.usage import RequestRecord, usage_fields
from app.tasks.context import InputChanged, LostLease
from _support.agent.model_stream_errors import client_for, stream


pytestmark = pytest.mark.asyncio
SECRET = 'private-error-detail-must-not-leak'


async def reserve(sessions, actor):
    async with sessions.begin() as db:
        row = ModelUsage(company_id=actor.company_id, owner_id=actor.id, kind='assistant', **usage_fields())
        db.add(row)
        await db.flush()
    return RequestRecord(sessions, row.id)


@pytest.mark.parametrize(('mode', 'code', 'state', 'message'), [
    ('attachment', 'business', 'unknown', '文件不可用或尚未发送'),
    ('permission', 'permission', 'unknown', '关联资料已变化或无权查看'),
    ('provider', 'invalid_response', 'failed', '模型未返回完整文字或有效工具调用'),
])
async def test_stream_callback_business_failure_is_not_provider_error(setup, monkeypatch, mode, code, state, message):
    settings, sessions, users, clients = setup
    requests = []
    def response(request):
        requests.append(request)
        return stream(
            {'usage': {'prompt_tokens': 12, 'completion_tokens': 3}},
            {'choices': [{'delta': {'content': '' if mode == 'provider' else '受控回复'}, 'finish_reason': 'stop'}]},
        )
    client_for(monkeypatch, response)
    async def validate_source(delta):
        if mode == 'attachment':
            problem(404, message)
        if mode == 'permission':
            problem(403, message, 'business_access_changed')
    record = await reserve(sessions, users['employee'])
    config = {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': True, 'parameters': {}}
    with pytest.raises(ProviderError if mode == 'provider' else HTTPException):
        await record.run(lambda event: chat(settings, config, SECRET, [{'role': 'user', 'content': '受控请求'}],
                                            on_event=event, on_delta=validate_source))
    result = (await clients['admin'].get('/api/v1/settings/model-usage')).json()
    item = result['items'][0]
    assert (item['errorCode'], item['error'], item['state']) == (code, message, state)
    assert item['inputTokens'] == 12 and item['outputTokens'] == 3
    assert item['startedAt'] and item['elapsedMs'] >= 0
    assert len(requests) == result['summary']['calls'] == 1
    assert result['summary']['states'][state] == 1
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize(('error', 'code', 'message', 'sent_state'), [
    (asyncio.CancelledError(SECRET), 'cancelled', '本次处理已取消', 'unknown'),
    (LostLease(SECRET), 'cancelled', '任务执行权已变化，本次处理已停止', 'unknown'),
    (InputChanged(document=True), 'input_changed', '文件提取版本已变化', 'unknown'),
    (DBAPIError('private SQL', {'secret': SECRET}, RuntimeError(SECRET)), 'database', '数据操作未完成', 'failed'),
    (RuntimeError(SECRET), 'internal_error', '内部处理未完成', 'failed'),
    (httpx.ReadTimeout(SECRET), 'timeout', '模型响应超时', 'unknown'),
    (httpx.ConnectError(SECRET), 'network', '未能连接模型服务', 'not_sent'),
    (ProviderError('content_filter', '模型服务内容审核未通过'), 'content_filter', '内容审核未通过', 'failed'),
])
@pytest.mark.parametrize('started', [False, True])
async def test_usage_classification_preserves_lifecycle_and_safe_messages(setup, error, code, message, sent_state, started):
    _, sessions, users, clients = setup
    record = await reserve(sessions, users['employee'])
    async def request(event):
        if started:
            await event('started')
        raise error
    with pytest.raises(type(error)) as caught:
        await record.run(request)
    assert caught.value is error
    # Late cleanup must not overwrite the recorded reason or mark it successful.
    await record.finish()
    result = (await clients['admin'].get('/api/v1/settings/model-usage')).json()
    item = result['items'][0]
    expected = sent_state if started else 'not_sent'
    assert item['errorCode'] == code and message in item['error'] and item['state'] == expected
    assert item['inputTokens'] is None and item['outputTokens'] is None
    assert result['summary']['calls'] == int(expected != 'not_sent')
    assert (item['elapsedMs'] is None) == (expected == 'not_sent')
    assert result['summary']['states'][expected] == 1
    assert SECRET not in json.dumps(result)
