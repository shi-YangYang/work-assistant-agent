"""A denied or exhausted public page must not discard other research results."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runtime.tool_nodes import tool_node
from app.agent.tools.resources.web import research, unavailable
from app.integrations import web_research
from app.tasks.context import BudgetExceeded, LostLease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.nodes.node_state import execution, node_dtos, save
from app.tasks.retry import NodeFailed
from _support.agent.business_actions import runtime
from _support.agent.task_retry import fast_nodes

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
    assert len(calls) == 2 and payload['state'] == 'unavailable' and payload['errorCode'] == 'web_network'
    assert payload['url'] == failed_url and 'text' not in payload
    assert payload['requestedUrl'] == failed_url and payload['sourceDiscovered']
    assert payload['evidenceLevel'] == 'search_snippet'
    assert payload['attemptsExhausted'] is True
    assert payload['availableEvidence'] == {'url': failed_url, 'title': '产品介绍', 'evidenceType': 'search_snippet'}
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        node = execution(job)['nodes'][-1]
        assert node['state'] == 'failed' and node['errorCode'] == 'web_network'
        assert node_dtos(job)[-1]['maxAttempts'] == 2
        assert node['attempts'] == 2 and node['totalRetries'] == 1 and not node['resumable']
        assert json.loads(node['output']['content']) == payload
        sources = job.result['webSources']
        assert sources[good_url]['evidenceType'] == 'page_text' and sources[good_url]['fetchState'] == 'read'
        assert sources[failed_url]['evidenceType'] == 'search_snippet' and sources[failed_url]['fetchState'] == 'unavailable'
    restored = await fetch_node(context, failed_url, transport)
    assert restored.content == failed.content and len(calls) == 2
    # A worker may stop after recording exhaustion but before its fallback is
    # saved. Recover that boundary without starting more network requests.
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        nodes = execution(job)
        nodes['nodes'][-1].pop('output')
        save(job, nodes)
    recovered = await fetch_node(context, failed_url, transport)
    assert recovered.content == failed.content and len(calls) == 2
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


@pytest.mark.parametrize('prompt', [
    '找两家发布机构各一个产品介绍链接即可。',
    '必须读取 https://example.org/required 的正文并总结，不接受其他页面代替。',
])
async def test_unverified_fetch_failure_preserves_other_sources_without_deciding_task_completion(setup, prompt):
    context, _ = await runtime(setup, prompt)
    sources = [
        {'url': 'https://publisher.example/product', 'title': 'Product', 'evidenceType': 'search_snippet'},
        {'url': 'https://another.example/product', 'title': 'Another product', 'evidenceType': 'page_link',
         'discoveredOn': 'https://another.example/'},
    ]
    async def found(_):
        return {'items': sources}
    await research(context, found, 'product')
    async with context.sessions() as db:
        before = (await db.get(Job, context.job_id)).result
    result = json.loads(await unavailable(context, 'https://example.org/required', 'Denied', is_fetch=True, code='http_403'))
    assert result['state'] == 'unavailable' and result['sourceDiscovered'] is False
    assert result['evidenceLevel'] == 'unverified_url' and 'availableEvidence' not in result and 'text' not in result
    assert '不是已检索来源' in result['nextStep'] and '其他已发现来源仍有效' in result['nextStep']
    assert '对照用户原请求' in result['nextStep'] and '只为尚缺的用户要求继续研究' in result['nextStep']
    assert '用户指定网址或正文仍须有对应证据' in result['nextStep']
    async with context.sessions() as db:
        # The same feedback preserves evidence for either request. It cannot
        # claim completion of an explicitly required URL/body or invalidate
        # sufficient links because an additional address failed.
        assert (await db.get(Job, context.job_id)).result == before


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


async def test_web_fetch_recovers_second_attempt_and_search_keeps_four_attempts(setup, fast_nodes):
    context = await enabled(setup)
    calls = []
    async def once(req):
        calls.append(req.url)
        if len(calls) == 1:
            raise httpx.ConnectTimeout('controlled', request=req)
        return httpx.Response(200, headers={'content-type': 'text/plain'}, text='Actual recovered passage')
    result = await fetch_node(context, 'https://example.org/recovered', httpx.MockTransport(once))
    assert json.loads(result.content)['text'] == 'Actual recovered passage' and len(calls) == 2
    searches = []
    async def temporary_search():
        searches.append(True)
        raise web_research.WebTemporaryError('controlled temporary error')
    result = await tool_node(context, request('web_search', 'new publisher', 'search'), temporary_search)
    assert len(searches) == 4 and json.loads(result.content)['state'] == 'unavailable'
    async with context.sessions() as db:
        nodes = node_dtos(await db.get(Job, context.job_id))
        assert [row['maxAttempts'] for row in nodes] == [2, 4]


async def test_interrupted_final_fetch_attempt_recovers_without_repeating_network(setup, fast_nodes):
    context = await enabled(setup)
    calls = []
    def good(req):
        calls.append(req.url)
        return httpx.Response(200, headers={'content-type': 'text/plain'}, text='Originally readable')
    url = 'https://example.org/interrupted'
    transport = httpx.MockTransport(good)
    await fetch_node(context, url, transport)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        journal = execution(job)
        row = journal['nodes'][-1]
        row.pop('output')
        row.update(state='running', attempts=2, nextAt=None)
        save(job, journal)
    result = json.loads((await fetch_node(context, url, transport)).content)
    assert len(calls) == 1 and result['attemptsExhausted'] and result['state'] == 'unavailable'
    assert result['errorCode'] == 'web_network' and result['availableEvidence']['evidenceType'] == 'page_text'
    assert '1 次自动重试' in result['message'] and 'text' not in result
    async with context.sessions() as db:
        node = execution(await db.get(Job, context.job_id))['nodes'][-1]
        assert node['state'] == 'failed' and node['attempts'] == 2 and 'output' in node


async def test_legacy_fetch_node_retains_original_attempt_policy(setup, fast_nodes):
    context = await enabled(setup)
    calls = []
    async def timeout(req):
        calls.append(req.url)
        raise httpx.ConnectTimeout('controlled', request=req)
    url = 'https://example.org/legacy'
    transport = httpx.MockTransport(timeout)
    await fetch_node(context, url, transport)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        journal = execution(job)
        row = journal['nodes'][-1]
        row.pop('output')
        row.pop('maxAttempts')
        row.update(state='running', errorCode='', attempts=2, nextAt=None)
        save(job, journal)
    result = json.loads((await fetch_node(context, url, transport)).content)
    assert len(calls) == 4 and result['attemptsExhausted'] and result['state'] == 'unavailable'
    async with context.sessions() as db:
        node = node_dtos(await db.get(Job, context.job_id))[-1]
        assert node['maxAttempts'] == 4 and node['attempts'] == 4


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


async def test_missing_page_match_never_creates_or_overwrites_read_evidence(setup):
    context = await enabled(setup)
    url = 'https://example.org/product'
    transport = httpx.MockTransport(lambda _: httpx.Response(200, headers={'content-type': 'text/plain'}, text='The plan may change.'))
    async def read(query):
        return await research(context, lambda value: web_research.web_fetch(value, find=query, transport=transport), url, is_fetch=True)
    missing = json.loads(await read('unrelated'))
    assert missing['state'] == 'not_found' and 'text' not in missing
    async with context.sessions() as db:
        assert not (await db.get(Job, context.job_id)).result.get('webSources')
    found = json.loads(await read('plan'))
    assert found['text'] == 'The plan may change.'
    async with context.sessions() as db:
        previous = (await db.get(Job, context.job_id)).result['webSources'][url]
    await read('unrelated')
    async with context.sessions() as db:
        source = (await db.get(Job, context.job_id)).result['webSources'][url]
        assert source == previous and source['evidenceType'] == 'page_text'
        assert source['fetchState'] == 'read' and source['endOffset'] == len(found['text'])


async def test_observed_page_link_is_durable_but_never_counts_as_a_read_target(setup):
    context = await enabled(setup)
    home, target = 'https://publisher.example/', 'https://publisher.example/product'
    def response(req):
        if str(req.url) == target:
            return httpx.Response(403)
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='<main><a href="/product">New product</a></main>')
    transport = httpx.MockTransport(response)
    await fetch_node(context, home, transport, 'index')
    unavailable = json.loads((await fetch_node(context, target, transport, 'denied-target')).content)
    assert unavailable['sourceDiscovered'] and unavailable['evidenceLevel'] == 'page_link'
    assert 'text' not in unavailable and '未取得网页正文' in unavailable['coverage']
    async with context.sessions() as db:
        source = (await db.get(Job, context.job_id)).result['webSources'][target]
        assert source['evidenceType'] == 'page_link' and source['discoveredOn'] == home
        assert source['fetchState'] == 'unavailable' and source['fetchError'] == 'http_403'
    readable = httpx.MockTransport(lambda _: httpx.Response(200, headers={'content-type': 'text/plain'}, text='Product description'))
    await fetch_node(context, target, readable, 'read-target')
    # Reading the index again must not downgrade or taint a previously read target.
    await fetch_node(context, home, transport, 'index-again')
    async with context.sessions() as db:
        source = (await db.get(Job, context.job_id)).result['webSources'][target]
        assert source['evidenceType'] == 'page_text' and source['fetchState'] == 'read'
        assert 'fetchError' not in source
