"""A denied or exhausted public page must not discard other research results."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runtime.tool_nodes import tool_node
from app.agent.tools.web import research
from app.integrations import web_research
from app.tasks.context import BudgetExceeded, LostLease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.nodes.node_state import execution, save
from app.tasks.retry import NodeFailed
from test_business_actions import runtime
from test_task_retry import fast_nodes

pytestmark = pytest.mark.asyncio


def request(name, value, call_id='fetch'):
    args = {'url' if name == 'web_fetch' else 'query': value}
    call = {'name': name, 'args': args, 'id': call_id, 'type': 'tool_call'}
    return SimpleNamespace(tool_call=call, state={'messages': [AIMessage(id='research-batch', content='', tool_calls=[call])]})


async def enabled(setup):
    context, _ = await runtime(setup, '查两家产品介绍，给链接即可')
    context.node_retry = True
    await initialize(context, 'research-input')
    return context


async def fetch_node(context, url, transport, call_id='fetch'):
    async def operation():
        content = await research(context, lambda value: web_research.web_fetch(value, transport=transport), url, is_fetch=True)
        return ToolMessage(content=content, tool_call_id=call_id, name='web_fetch')
    return await tool_node(context, request('web_fetch', url, call_id), operation)


async def test_exhausted_web_network_returns_durable_unavailable_and_keeps_other_sources(setup, fast_nodes):
    context = await enabled(setup)
    failed_url, good_url = 'https://example.org/restricted', 'https://example.net/product'
    async def found(_):
        return {'items': [{'url': failed_url, 'title': '产品介绍', 'snippet': '搜索摘要', 'evidenceType': 'search_snippet'}]}
    await research(context, found, '产品介绍')
    good = httpx.MockTransport(lambda _: httpx.Response(200, headers={'content-type': 'text/plain'}, text='已读取的官方产品说明'))
    first = await fetch_node(context, good_url, good, 'good')
    assert json.loads(first.content)['text'] == '已读取的官方产品说明'
    calls = []
    async def timeout(req):
        calls.append(req.url)
        raise httpx.ReadTimeout('controlled timeout', request=req)
    transport = httpx.MockTransport(timeout)
    failed = await fetch_node(context, failed_url, transport)
    payload = json.loads(failed.content)
    assert len(calls) == 4 and payload['state'] == 'unavailable' and payload['errorCode'] == 'web_network'
    assert payload['url'] == failed_url and 'text' not in payload
    assert payload['requestedUrl'] == failed_url and payload['sourceDiscovered']
    assert payload['evidenceLevel'] == 'search_snippet'
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        node = execution(job)['nodes'][-1]
        assert node['state'] == 'failed' and node['errorCode'] == 'web_network'
        assert node['attempts'] == 4 and node['totalRetries'] == 3 and not node['resumable']
        assert json.loads(node['output']['content']) == payload
        sources = job.result['webSources']
        assert sources[good_url]['evidenceType'] == 'page_text' and sources[good_url]['fetchState'] == 'read'
        assert sources[failed_url]['evidenceType'] == 'search_snippet' and sources[failed_url]['fetchState'] == 'unavailable'
    restored = await fetch_node(context, failed_url, transport)
    assert restored.content == failed.content and len(calls) == 4
    # A worker may stop after recording exhaustion but before its fallback is
    # saved. Recover that boundary without starting four more network requests.
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        nodes = execution(job)
        nodes['nodes'][-1].pop('output')
        save(job, nodes)
    recovered = await fetch_node(context, failed_url, transport)
    assert recovered.content == failed.content and len(calls) == 4
    # A later read still runs normally; only the failed page node is terminal.
    next_page = await fetch_node(context, good_url + '/next', good, 'next')
    assert json.loads(next_page.content)['evidenceType'] == 'page_text'


@pytest.mark.parametrize('status,location,code', [(403, None, 'http_403'), (302, 'http://localhost/secret', 'blocked_url')])
async def test_denied_and_unsafe_redirects_are_unavailable_without_retries(setup, status, location, code):
    context = await enabled(setup)
    calls = []
    def denied(req):
        calls.append(req.url)
        return httpx.Response(status, headers={'location': location} if location else {})
    result = await fetch_node(context, 'https://example.org/product', httpx.MockTransport(denied))
    payload = json.loads(result.content)
    assert payload['state'] == 'unavailable' and payload['errorCode'] == code and len(calls) == 1
    assert payload['requestedUrl'] == 'https://example.org/product'
    assert payload['sourceDiscovered'] is False and payload['evidenceLevel'] == 'unverified_url'
    assert '不是已检索来源' in payload['nextStep']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert not job.result.get('webSources')
        node = execution(job)['nodes'][-1]
        assert node['state'] == 'failed' and node['attempts'] == 1


@pytest.mark.parametrize('error', [asyncio.CancelledError(), LostLease(), BudgetExceeded('budget'), HTTPException(403, 'no access')])
async def test_research_fallback_never_swallows_hard_stop_or_authorization(setup, fast_nodes, error):
    context = await enabled(setup)
    calls = []
    async def operation():
        calls.append(True)
        raise error
    with pytest.raises(asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else NodeFailed):
        await tool_node(context, request('web_fetch', 'https://example.org'), operation)
    assert len(calls) == 1
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert 'output' not in execution(job)['nodes'][-1] and not job.result.get('webSources')


async def test_non_web_tool_does_not_use_optional_web_fallback(setup, fast_nodes):
    context = await enabled(setup)
    calls = []
    async def operation():
        calls.append(True)
        raise web_research.WebTemporaryError('controlled temporary error')
    with pytest.raises(NodeFailed) as caught:
        await tool_node(context, request('find_work_items', '产品'), operation)
    assert caught.value.failure.code == 'web_network' and len(calls) == 4


async def test_failed_followup_read_and_later_search_preserve_successful_excerpt(setup):
    context = await enabled(setup)
    url = 'https://example.org/product'
    good = httpx.MockTransport(lambda _: httpx.Response(200, headers={'content-type': 'text/plain'}, text='x' * 4000))
    result = json.loads((await fetch_node(context, url, good, 'first')).content)
    assert result['truncated'] and result['nextOffset'] == 3000
    denied = httpx.MockTransport(lambda _: httpx.Response(403))
    await fetch_node(context, url, denied, 'later')
    async def search(_):
        return {'items': [{'url': url, 'title': '搜索标题', 'evidenceType': 'search_snippet'}]}
    await research(context, search, '产品')
    async with context.sessions() as db:
        source = (await db.get(Job, context.job_id)).result['webSources'][url]
        assert source['evidenceType'] == 'page_text' and source['truncated']
        assert source['offset'] == 0 and source['nextOffset'] == 3000
        assert source['fetchState'] == 'unavailable' and source['fetchError'] == 'http_403'
