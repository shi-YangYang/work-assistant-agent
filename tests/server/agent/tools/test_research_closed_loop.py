"""Closed-research recovery and the actual framework-to-HTTP tool binding."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.harness import build_graph
from app.agent.runtime.middleware import ToolBoundary
from app.agent.runtime.tool_progress import begin, end
from app.agent.runtime.tool_progress.service import research_stopped
from app.agent.tools.catalog import remember_groups
from app.tasks.budget import service as budget
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from _support.agent.business_actions import runtime
from _support.agent.model_stream_errors import client_for, stream

pytestmark = pytest.mark.asyncio


async def closed_context(setup):
    context, _ = await runtime(setup, 'Search the requested public sources')
    context.node_retry = True
    await initialize(context, 'research-loop')
    for index in range(6):
        call = {'id': str(index), 'name': 'web_search', 'args': {'query': str(index)}}
        assert await begin(context, call) is None
        await end(context, call, ToolMessage(tool_call_id=call['id'], content='{"items": []}'))
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert research_stopped(context, job)
        remember_groups(context, job, ['research', 'documents', 'work'])
    return context


def research_batch(identifier='closed-batch', extra=()):
    return AIMessage(id=identifier, content='', tool_calls=[
        {'id': identifier + '-search', 'name': 'web_search', 'args': {'query': 'another query'}},
        {'id': identifier + '-fetch', 'name': 'web_fetch', 'args': {'url': 'https://example.org/other'}},
        *extra,
    ])


async def dispatch(context, batch, handler=None):
    handler = handler or AsyncMock(side_effect=AssertionError('Closed IO must not execute'))
    messages = [HumanMessage(content='Search the requested public sources'), batch]
    for call in batch.tool_calls:
        request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call=call,
                                  state={'messages': messages[:2]})
        messages.append(await ToolBoundary().awrap_tool_call(request, handler))
    return messages


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('phase', ['closed', 'finalizing', 'rejected', 'protocol'])
async def test_real_graph_binding_reaches_http_with_filtered_schemas_and_explicit_none(setup, monkeypatch, phase, streaming):
    context = await closed_context(setup)
    messages = [HumanMessage(content='Search the requested public sources')]
    if phase == 'finalizing':
        async with context.sessions.begin() as db:
            budget.finalize(await db.get(Job, context.job_id), context, 'no_progress')
    elif phase == 'rejected':
        messages = await dispatch(context, research_batch())
    elif phase == 'protocol':
        messages.append(HumanMessage(id=f'delivery-repair:{context.job_id}', content='Repair prose only'))
    requests = []
    async def resolve(*args):
        return {'baseUrl': 'https://example.org/v1', 'model': 'controlled', 'streaming': streaming, 'parameters': {}}, 'unused'
    def capture(request):
        requests.append(json.loads(request.content))
        if streaming:
            return stream({'choices': [{'index': 0, 'delta': {'content': 'Available sources retained.'}, 'finish_reason': None}]},
                          {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                           'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
        return httpx.Response(200, json={'id': 'controlled-http', 'model': 'controlled', 'object': 'chat.completion',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'Available sources retained.'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    client_for(monkeypatch, capture)
    await build_graph(context.settings, None, context).ainvoke({'messages': messages}, context=context)
    assert len(requests) == 1
    body = requests[0]
    names = {item['function']['name'] for item in body.get('tools', [])}
    assert not names & {'web_search', 'web_fetch'}
    if phase == 'closed':
        assert {'load_tools', 'read_document', 'get_work_item'} <= names
        assert body['tool_choice'] == 'auto'
    else:
        assert not names and body['tool_choice'] == 'none'


async def settle(context, messages):
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        research_stopped(context, job, messages)
        return job.result


async def test_closed_batch_requires_all_receipts_and_recovery_is_idempotent(setup):
    context = await closed_context(setup)
    messages = await dispatch(context, research_batch())
    partial = await settle(context, messages[:-1])
    assert partial['taskBudget']['phase'] != 'finalizing'
    saved = await settle(context, messages)
    assert saved['taskBudget']['phase'] == 'finalizing' and saved['taskBudget']['reason'] == 'no_progress'
    assert saved['taskBudget']['models'] == 0 and saved['taskBudget']['tools'] == 0
    assert await settle(replace(context), messages) == saved
    replayed = await dispatch(replace(context), messages[1])
    assert [message.content for message in replayed[2:]] == [message.content for message in messages[2:]]
    assert await settle(context, replayed) == saved


@pytest.mark.parametrize('kind', ['cached_page', 'business', 'business_failure'])
@pytest.mark.parametrize('sibling_first', [False, True])
async def test_valid_sibling_keeps_business_and_cached_read_path_open(setup, kind, sibling_first):
    context = await closed_context(setup)
    if kind == 'cached_page':
        url = 'https://example.org/saved'
        page = {'url': url, 'text': 'A retained paragraph'}
        await context.web_pages.get(url, AsyncMock(return_value=page))
        extra = {'name': 'web_fetch', 'id': 'valid', 'args': {'url': url, 'find': 'retained'}}
    else:
        # Use an actual business tool at the boundary, with a controlled result.
        extra = {'name': 'get_work_item', 'id': 'valid', 'args': {'work_id': 'controlled'}}
        page = {'state': 'unavailable'} if kind == 'business_failure' else {'id': 'controlled', 'body': 'Read work'}
    batch = research_batch(extra=[extra])
    if sibling_first:
        batch.tool_calls = [batch.tool_calls[-1], *batch.tool_calls[:-1]]
    handler = AsyncMock(return_value=ToolMessage(tool_call_id='valid', content=json.dumps(page)))
    messages = await dispatch(context, batch, handler)
    handler.assert_awaited_once()
    saved = await settle(context, messages)
    assert saved['taskBudget']['phase'] != 'finalizing'
    assert not saved['toolProgress']['stopped']
    # A subsequent wholly forbidden batch is still bounded; the valid sibling
    # does not permanently disable the dead-end recovery path.
    repeated = await dispatch(context, research_batch('next-closed-batch'))
    assert (await settle(context, repeated))['taskBudget']['phase'] == 'finalizing'
