"""Deterministic tool-boundary tests; real model comparisons run separately."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.runtime.middleware import ToolBoundary
from app.agent.runtime.tool_progress import begin, end
from app.agent.runtime.tool_progress.service import research_stopped, web_cache
from app.agent.tools.catalog import allowed_tools, load_tools, remember_groups
from app.core.digests import digest
from app.integrations.web_research import WebResearchError
from app.tasks.models import Job
from _support.agent.business_actions import create, runtime


def query(identifier):
    return {'name': 'web_search', 'args': {'query': identifier}, 'id': identifier}


async def finish(context, call, result):
    assert await begin(context, call) is None
    return await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps(result)))


async def stopped(context):
    async with context.sessions.begin() as db:
        return research_stopped(context, await db.get(Job, context.job_id))


@pytest.mark.asyncio
@pytest.mark.parametrize('success_first', [False, True])
async def test_complete_batch_progress_wins_over_sibling_failures_in_any_order(setup, success_first):
    context, _ = await runtime(setup)
    for index in range(5):
        await finish(context, query(f'empty-{index}'), {'items': []})
    peers = [f'batch-{index}' for index in range(8)]
    calls = [{**query(identifier), 'progressBatch': 'parallel', 'progressPeers': peers} for identifier in peers]
    outcomes = [(call, {'items': []}) for call in calls[:-1]]
    successful = (calls[-1], {'items': [{'url': 'https://example.org/new', 'title': 'New', 'snippet': 'Fact'}]})
    outcomes = [successful, *outcomes] if success_first else [*outcomes, successful]
    # Some siblings have not even entered their begin() when the first finishes.
    for call, result in outcomes:
        await finish(context, call, result)
        if call != outcomes[-1][0]:
            assert not await stopped(context)
    assert not await stopped(context)
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']
        assert journal['research']['stalled'] == 0
        assert journal['stalled'] == 0 and not journal['stopped']


@pytest.mark.asyncio
async def test_research_closure_is_durable_replay_free_and_does_not_close_business_tools(setup):
    context, _ = await runtime(setup)
    calls = [query(f'empty-{index}') for index in range(6)]
    for call in calls:
        await finish(context, call, {'items': []})
        await finish(context, {'name': 'get_work_item', 'args': {'work_id': call['id']}, 'id': 'work-' + call['id']},
                     {'id': call['id'], 'body': 'Read work'})
    assert await stopped(context)
    async with context.sessions() as db:
        saved = (await db.get(Job, context.job_id)).result['toolProgress']
        assert saved['research']['stalled'] == 6
    # Restoring a previously executed request retains its original decision;
    # its actual node is responsible for replaying the saved output.
    await finish(replace(context), calls[0], {'items': []})
    assert await stopped(context)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['toolProgress'] == saved
        assert job.result.get('taskBudget', {}).get('phase') != 'finalizing'
    for call in (query('new-wording'), {'name': 'web_fetch', 'args': {'url': 'https://example.org/new'}, 'id': 'new-page'}):
        assert json.loads((await begin(context, call)).content)['code'] == 'research_no_progress'
    assert await begin(context, {'name': 'save_deliverable', 'args': {'title': 'Summary'}, 'id': 'save'}) is None
    assert await begin(context, {'name': 'execute_business_action', 'args': {'step': 1}, 'id': 'work'}) is None
    assert await begin(replace(context, node_scope='new-user-input'), query('new-wording')) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('code,exhausted', [('http_404', False), ('http_410', False), ('web_network', True)])
async def test_terminal_failure_survives_call_eviction_changed_dependencies_and_refresh(setup, code, exhausted):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/page#one'}, 'id': 'failed'}
    content = {'state': 'unavailable', 'errorCode': code, 'attemptsExhausted': exhausted}
    original = await finish(context, call, content)
    for index in range(34):
        await finish(context, {'name': 'get_work_item', 'args': {'work_id': str(index)}, 'id': str(index)},
                     {'id': str(index), 'body': 'Work'})
    async with context.sessions() as db:
        before = (await db.get(Job, context.job_id)).result['toolProgress']
    replay = await finish(context, call, content)
    assert replay.content == original.content
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['toolProgress'] == before
    work = await create(setup[3]['employee'])
    context.read_versions[work['id']] = work['revision']
    changed = {**call, 'id': 'retry', 'args': {'url': 'https://example.org/page#two', 'find': 'other', 'refresh': True}}
    assert await begin(context, changed)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert not any(row['id'] == 'failed' for row in job.result['toolProgress']['calls'])
        job.attempt += 1
    assert await begin(context, changed) is None


@pytest.mark.asyncio
async def test_new_page_text_resets_progress_but_empty_or_identical_body_does_not(setup):
    context, _ = await runtime(setup)
    for index in range(5):
        await finish(context, query(str(index)), {'items': []})
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/page'}, 'id': 'body'}
    body = {'url': call['args']['url'], 'text': 'Actual page text', 'nextOffset': 30}
    await finish(context, call, body)
    assert not await stopped(context)
    await finish(context, {**call, 'id': 'refresh', 'args': {**call['args'], 'refresh': True}}, {**body, 'fetchedAt': 'new-time'})
    assert not await stopped(context)
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['toolProgress']['research']['stalled'] == 1
    await finish(context, {**call, 'id': 'miss', 'args': {**call['args'], 'find': 'absent'}}, {'state': 'not_found'})
    assert not await stopped(context)
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['toolProgress']['research']['stalled'] == 2


async def model_tools(context):
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), tools=[{'name': name} for name in allowed_tools(context)],
                              messages=[HumanMessage(content='Search and summarize')], system_message=SystemMessage(content='Base'))
    request.override = lambda **kwargs: SimpleNamespace(**kwargs)
    return await ToolBoundary().awrap_model_call(request, AsyncMock(side_effect=lambda value: value))


@pytest.mark.asyncio
async def test_model_and_invocation_boundaries_allow_only_cached_reads_after_closure(setup, monkeypatch):
    context, _ = await runtime(setup)
    for index in range(6):
        await finish(context, query(str(index)), {'items': []})
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        remember_groups(context, job, ['research', 'documents'])
    monkeypatch.setattr('app.agent.actions.interactions.waiting_text', AsyncMock(return_value=None))
    monkeypatch.setattr('app.agent.completion.completion.receipt_completion', AsyncMock(return_value=False))
    offered = await model_tools(context)
    names = [tool.get('name', tool.get('function', {}).get('name')) for tool in offered.tools]
    assert 'web_search' not in names and 'web_fetch' not in names and 'read_document' in names
    assert 'research' not in offered.tools[0]['function']['parameters']['properties']['groups']['items']['enum']
    result = json.loads(await load_tools.coroutine(['research'], SimpleNamespace(context=context)))
    assert result['state'] == 'unavailable' and 'research' not in result['available']

    now = [100.0]
    context.web_pages.clock = lambda: now[0]
    url = 'https://example.org/cached'
    page = {'text': 'Cached body'}
    await context.web_pages.get(url, AsyncMock(return_value=page))
    offered = await model_tools(context)
    assert 'web_fetch' in [tool.get('name') for tool in offered.tools]
    call = {'name': 'web_fetch', 'args': {'url': url, 'find': 'new phrase'}, 'id': 'cached'}
    assert await begin(context, call) is None
    readonly = await web_cache(context)
    download = AsyncMock(side_effect=AssertionError('Network must never run'))
    assert await readonly.get(url, download) == (page, True)
    for key, refresh in ((url, True), ('https://example.org/miss', False)):
        with pytest.raises(WebResearchError, match='停止联网'):
            await readonly.get(key, download, refresh=refresh)
    now[0] += 121
    with pytest.raises(WebResearchError, match='停止联网'):
        await readonly.get(url, download)
    download.assert_not_awaited()
    assert json.loads((await begin(context, {**call, 'id': 'expired'})).content)['code'] == 'research_no_progress'


@pytest.mark.asyncio
async def test_actual_tool_boundary_passes_full_batch_peers_before_any_sibling_finishes(setup):
    context, _ = await runtime(setup)
    context.node_retry = True
    from app.tasks.nodes.node_execution import initialize
    await initialize(context, 'research-batch')
    for index in range(5):
        await finish(context, query(str(index)), {'items': []})
    calls = [query('failed'), query('successful')]
    batch = AIMessage(id='parallel-model', content='', tool_calls=calls)
    gate = asyncio.Event()
    async def handler(request):
        if request.tool_call['id'] == 'successful':
            await gate.wait()
            result = {'items': [{'url': 'https://example.org/new'}]}
        else:
            result = {'items': []}
        return ToolMessage(tool_call_id=request.tool_call['id'], content=json.dumps(result))
    def request(call):
        return SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call=call, state={'messages': [batch]})
    boundary = ToolBoundary()
    first = await boundary.awrap_tool_call(request(calls[0]), handler)
    assert first and not await stopped(context)
    gate.set()
    await boundary.awrap_tool_call(request(calls[1]), handler)
    assert not await stopped(context)
    async with context.sessions() as db:
        research = (await db.get(Job, context.job_id)).result['toolProgress']['research']
        peers = {digest({'message': batch.id, 'call': call['id']}) for call in calls}
        assert set(research['batches'][-1]['calls']) == peers
        assert research['stalled'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', [False, True])
async def test_actual_new_page_link_counts_as_evidence_even_when_destination_body_fails(setup, failed):
    context, _ = await runtime(setup)
    for index in range(5):
        await finish(context, query(f'empty-{index}'), {'items': []})
    link = {'url': 'https://example.org/product', 'title': 'Product', 'evidenceType': 'page_link',
            'discoveredOn': 'https://example.org/official', 'discoveryType': 'http_redirect'}
    content = {'links': [link]}
    if failed:
        content.update(state='unavailable', errorCode='http_403')
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/official'}, 'id': 'discovery'}
    await finish(context, call, content)
    assert not await stopped(context)
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']['research']
        assert journal['stalled'] == 0
    # A later receipt can repeat the saved redirect with different timestamps.
    repeated = {'name': 'web_fetch', 'args': {'url': 'https://example.org/another-read'}, 'id': 'repeated-link'}
    await finish(context, repeated, {'links': [{**link, 'fetchedAt': 'later', 'cacheHit': True}]})
    assert not await stopped(context)
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']['research']
        assert journal['stalled'] == 1 and len(journal['evidence']) == 1
