"""Provider stream errors must keep their meaning through parsing and retries."""
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.integrations.models.chat import chat
from app.integrations.models.transport import ProviderError
from app.modules.model_services.models import ModelUsage
from app.tasks.processing.handlers import process_job
from app.tasks.nodes.node_failures import classify
from app.tasks.runtime.queue import claim
from app.tasks.retry import NodeFailed, run
from test_company import send
from test_model_services import create, route, SECRET

pytestmark = pytest.mark.asyncio
CONFIG = {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': True, 'parameters': {}}


def stream(*events, done=True):
    data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)
    return httpx.Response(200, text=data + ('data: [DONE]\n\n' if done else ''), headers={'Content-Type': 'text/event-stream'})


def client_for(monkeypatch, handler):
    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize('mode', ['stream_error', 'json_error', 'http_error', 'finish_reason'])
async def test_content_review_rejection_is_not_parameter_error_or_retryable(monkeypatch, mode):
    # Upstream prose can echo credentials; expose only our fixed safe message.
    detail = {'error': {'code': 'data_inspection_failed', 'message': 'Output data may contain inappropriate content. ' + SECRET}}
    def response(request):
        if mode == 'http_error':
            return httpx.Response(400, json=detail)
        if mode == 'json_error':
            return httpx.Response(200, json=detail)
        if mode == 'finish_reason':
            return stream({'choices': [{'delta': {}, 'finish_reason': 'content_filter'}]}, done=False)
        # Even a complete-looking tool call preceding rejection cannot execute.
        partial = {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'rejected', 'function': {'name': 'web_fetch', 'arguments': '{"url":"https://example.org"}'}}]}}]}
        return stream(partial, detail)
    client_for(monkeypatch, response)
    with pytest.raises(ProviderError) as failure:
        await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': mode != 'json_error'}, SECRET, [{'role': 'user', 'content': '查询公开新闻'}])
    assert failure.value.code == 'content_filter'
    assert '内容审核' in str(failure.value) and '参数' not in str(failure.value)
    assert SECRET not in str(failure.value)
    assert not classify(failure.value).retryable


@pytest.mark.parametrize(('code', 'category', 'retries'), [
    ('DataInspectionFailed', 'content_filter', 0),
    ('rate_limit_exceeded', 'rate_limit', 1),
    ('server_error', 'network', 1),
    ('invalid_request_error', 'protocol', 0),
    ('insufficient_quota', 'quota', 0),
    ('unknown_provider_code', 'provider_error', 0),
])
async def test_retry_policy_uses_structured_stream_errors(monkeypatch, code, category, retries):
    calls, delays = [], []
    def response(request):
        calls.append(True)
        if len(calls) == 1:
            return stream({'error': {'type': code, 'message': SECRET}})
        return stream({'choices': [{'delta': {'content': '完成'}, 'finish_reason': 'stop'}]})
    client_for(monkeypatch, response)
    async def request():
        return await chat(SimpleNamespace(model_allowed_origins=()), CONFIG, SECRET, [{'role': 'user', 'content': '查询公开资料'}])
    async def noop(*args):
        pass
    clock = [0.0]
    async def wait(delay):
        clock[0] += delay
        delays.append(delay)
    operation = run(request, classify=classify, before=noop, emit=noop, wait=wait, clock=lambda: clock[0])
    if retries:
        result = await operation
        assert result['choices'][0]['message']['content'] == '完成'
        assert delays
    else:
        with pytest.raises(NodeFailed) as failure:
            await operation
        assert failure.value.failure.code == category
        assert SECRET not in str(failure.value)
        assert delays == []
    assert len(calls) == retries + 1


async def test_web_search_then_review_rejection_reaches_job_nodes_and_usage(setup, monkeypatch):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    routing = await clients['admin'].put('/api/v1/settings/model-routing', json=route(saved))
    assert routing.status_code == 200, routing.text
    calls, searches = [], []
    async def search(query):
        searches.append(query)
        return {'query': query, 'items': [{'title': '公开信息', 'url': 'https://example.org/news', 'snippet': '公开新闻摘要'}]}
    monkeypatch.setattr('app.integrations.web_research.web_search', search)
    def response(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return stream({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'search-1', 'function': {'name': 'web_search', 'arguments': '{"query":"国内新闻"}'}}]}, 'finish_reason': 'tool_calls'}]})
        assert any(m['role'] == 'tool' and '公开新闻摘要' in m['content'] for m in body['messages'])
        return stream({'error': {'code': 'data_inspection_failed', 'message': 'Output data may contain inappropriate content. ' + SECRET}})
    client_for(monkeypatch, response)
    sent = await send(clients['employee'], '连网搜索一下最近的国内新闻')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(await claim(sessions, users['employee'].id), sessions, settings, saver)
    detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['state'] == 'awaiting_retry', detail
    assert '内容审核' in detail['job']['error'] and '参数' not in detail['job']['error']
    assert not detail['reply'] and not detail['drafts']
    assert searches == ['国内新闻'] and len(calls) == 2
    failed = [node for node in detail['job']['nodes'] if node['state'] == 'failed']
    assert len(failed) == 1 and failed[0]['errorCode'] == 'content_filter' and failed[0]['attempts'] == 1
    assert SECRET not in json.dumps(detail)
    async with sessions() as db:
        usage = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == sent['jobId']).order_by(ModelUsage.created_at))).all()
        assert [item.status for item in usage] == ['succeeded', 'failed']
        assert usage[-1].error_code == 'content_filter' and SECRET not in usage[-1].error_message
