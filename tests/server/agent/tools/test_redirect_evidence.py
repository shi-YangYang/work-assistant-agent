"""Observed HTTP redirects survive downstream failures as link-only evidence."""
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runtime.tool_nodes import tool_node
from app.agent.runtime.tool_progress import begin, end
from app.agent.tools.resources.web import research, unavailable
from app.integrations import web_research
from app.modules.messages.references.web_sources import web_citations
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.nodes.node_state import execution, save
from _support.agent.business_actions import runtime
from _support.agent.task_retry import fast_nodes

pytestmark = pytest.mark.asyncio

ORIGIN = 'https://publisher.example/product'
TARGET = 'https://product.example/'
LINK = {'url': TARGET, 'title': 'product.example', 'evidenceType': 'page_link',
        'discoveryType': 'http_redirect', 'discoveredOn': ORIGIN, 'fetchState': 'not_read'}


def redirected_transport(failure, calls):
    def response(request):
        calls.append(str(request.url))
        if str(request.url) == ORIGIN:
            return httpx.Response(301, headers={'location': TARGET, 'set-cookie': 'private=secret'})
        if failure == 'timeout':
            raise httpx.ReadTimeout('controlled downstream failure', request=request)
        if failure == 'private_dns':
            raise web_research.WebResearchError('non-public address', code='blocked_url')
        if failure == 'dns':
            raise web_research.WebTemporaryError(category='dns')
        return httpx.Response(failure, headers={'content-type': 'text/plain'}, text='Actual body')
    return httpx.MockTransport(response)


@pytest.mark.parametrize('failure,code,category', [(403, 'http_403', ''), ('timeout', 'unavailable', 'timeout')])
async def test_failed_redirect_retains_observed_location_only(failure, code, category):
    calls = []
    with pytest.raises(web_research.WebResearchError) as caught:
        await web_research.web_fetch(ORIGIN, transport=redirected_transport(failure, calls))
    assert caught.value.links == [LINK]
    assert caught.value.failed_url == TARGET
    assert caught.value.code == code and caught.value.category == category
    assert calls == [ORIGIN, TARGET]
    assert 'private' not in json.dumps(caught.value.links)


@pytest.mark.parametrize('target', ['http://127.0.0.1/private', 'file:///etc/passwd', 'https://user:password@example.org/'])
async def test_invalid_redirect_does_not_become_evidence_or_request(target):
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': target})
    with pytest.raises(web_research.WebResearchError) as caught:
        await web_research.web_fetch(ORIGIN, transport=httpx.MockTransport(response))
    assert caught.value.code == 'blocked_url' and caught.value.links == []
    assert caught.value.failed_url == ''
    assert calls == [ORIGIN]


@pytest.mark.parametrize('failure', ['private_dns', 'dns'])
async def test_redirect_with_rejected_or_unresolved_dns_is_not_promoted(failure):
    with pytest.raises(web_research.WebResearchError) as caught:
        await web_research.web_fetch(ORIGIN, transport=redirected_transport(failure, []))
    assert caught.value.links == []
    assert caught.value.failed_url == ''


async def test_later_unsafe_redirect_does_not_erase_previously_observed_safe_hop():
    def response(request):
        return httpx.Response(302, headers={'location': TARGET if str(request.url) == ORIGIN else 'http://localhost/private'})
    with pytest.raises(web_research.WebResearchError) as caught:
        await web_research.web_fetch(ORIGIN, transport=httpx.MockTransport(response))
    assert caught.value.code == 'blocked_url' and caught.value.links == [LINK]


async def test_successful_redirect_still_delivers_final_page_text():
    calls = []
    result = await web_research.web_fetch(ORIGIN, transport=redirected_transport(200, calls))
    assert result['requestedUrl'] == ORIGIN and result['url'] == TARGET
    assert result['evidenceType'] == 'page_text' and result['text'] == 'Actual body'
    assert not result.get('links') and calls == [ORIGIN, TARGET]


async def test_redirect_limit_does_not_claim_the_unrequested_destination_failed():
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': f'https://product.example/hop-{len(calls)}'})
    with pytest.raises(web_research.WebResearchError, match='跳转次数') as caught:
        await web_research.web_fetch(ORIGIN, transport=httpx.MockTransport(response))
    assert len(calls) == 4 and caught.value.failed_url == ''
    assert caught.value.links[-1]['url'] == 'https://product.example/hop-4'
    assert caught.value.links[-1]['url'] not in calls


@pytest.mark.parametrize('failure', [403, 'timeout'])
async def test_redirect_evidence_survives_retry_fallback_and_worker_replay(setup, fast_nodes, failure):
    context, _ = await runtime(setup, '给我产品介绍链接即可')
    context.node_retry = True
    await initialize(context, 'redirect-evidence-input')
    calls = []
    transport = redirected_transport(failure, calls)
    call = {'name': 'web_fetch', 'args': {'url': ORIGIN}, 'id': 'redirect', 'type': 'tool_call'}
    requested = SimpleNamespace(tool_call=call, state={'messages': [AIMessage(id='redirect-batch', content='', tool_calls=[call])]})
    async def operation():
        content = await research(context, lambda value: web_research.web_fetch(value, transport=transport), ORIGIN, is_fetch=True)
        return ToolMessage(content=content, tool_call_id='redirect', name='web_fetch')
    result = await tool_node(context, requested, operation)
    payload = json.loads(result.content)
    assert payload['links'] == [LINK] and payload['sourceDiscovered'] is True
    assert payload['evidenceLevel'] == 'page_link' and 'text' not in payload
    assert payload['availableEvidence']['redirectTo'] == TARGET and payload['failedUrl'] == TARGET
    assert '仅尝试该地址' not in payload['coverage']
    expected = [ORIGIN, TARGET] * (2 if failure == 'timeout' else 1)
    assert calls == expected
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        sources = job.result['webSources']
        assert sources[TARGET] == {**LINK, 'fetchState': 'unavailable', 'fetchError': payload['errorCode']}
        assert sources[ORIGIN] == {'url': ORIGIN, 'title': 'publisher.example', 'evidenceType': 'page_link',
                                   'discoveryType': 'http_redirect', 'redirectTo': TARGET, 'fetchState': 'redirected'}
        assert job.result['webRedirects'] == {ORIGIN: [LINK]}
        assert web_citations(job.result) == []
    assert (await tool_node(context, requested, operation)).content == result.content
    assert calls == expected
    # A later attempt at the discovered target is honest about discovery but
    # must not claim that its body was already read.
    later = json.loads(await unavailable(context, TARGET, 'Denied', is_fetch=True, code='http_403'))
    assert later['sourceDiscovered'] and later['evidenceLevel'] == 'page_link'
    assert later['availableEvidence']['discoveredOn'] == ORIGIN and 'text' not in later
    if failure == 'timeout':
        # The worker can recover after saving exhaustion but before fallback.
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            state = execution(job)
            state['nodes'][-1].pop('output')
            save(job, state)
        recovered = await tool_node(context, requested, operation)
        assert recovered.content == result.content and calls == expected


@pytest.mark.parametrize('failure', [403, 'timeout'])
async def test_failed_redirect_target_cannot_restart_attempts_and_new_input_can(setup, fast_nodes, failure):
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'redirect-input')
    calls = []
    transport = redirected_transport(failure, calls)
    async def fetch(url, identifier, **args):
        call = {'name': 'web_fetch', 'args': {'url': url, **args}, 'id': identifier, 'type': 'tool_call'}
        blocked = await begin(context, call)
        if blocked:
            return blocked
        request = SimpleNamespace(tool_call=call, state={'messages': [AIMessage(id=identifier, content='', tool_calls=[call])]})
        async def operation():
            result = await research(context, lambda value: web_research.web_fetch(value, transport=transport, **args), url, is_fetch=True)
            return ToolMessage(content=result, tool_call_id=identifier, name='web_fetch')
        return await end(context, call, await tool_node(context, request, operation))
    first = await fetch(ORIGIN, 'origin')
    expected = [ORIGIN, TARGET] * (2 if failure == 'timeout' else 1)
    assert json.loads(first.content)['failedUrl'] == TARGET and calls == expected
    for identifier, args in (('target', {}), ('target-refresh', {'refresh': True, 'find': 'product'})):
        result = await fetch(TARGET.rstrip('/') + '#same-page', identifier, **args)
        assert json.loads(result.content)['state'] == 'not_executed' and calls == expected
    await initialize(context, 'new-user-input')
    async with context.sessions() as db:
        result = (await db.get(Job, context.job_id)).result
        assert not {'webSources', 'webRedirects', 'webReadFailures'}.intersection(result)
    await fetch(TARGET, 'new-input')
    assert calls == [*expected, *([TARGET] * (2 if failure == 'timeout' else 1))]


async def test_failure_metadata_never_keeps_private_or_arbitrary_values(setup):
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'safe-failure-metadata')
    call = {'name': 'web_fetch', 'args': {'url': ORIGIN}, 'id': 'unsafe-metadata', 'type': 'tool_call'}
    request = SimpleNamespace(tool_call=call, state={'messages': [AIMessage(id='unsafe', content='', tool_calls=[call])]})
    async def operation():
        async def fail(_):
            error = web_research.WebResearchError('Rejected', code='blocked_url')
            error.failed_url = 'http://127.0.0.1/private'
            error.links = [{**LINK, 'url': 'http://localhost/private'}, {'url': TARGET, 'discoveredOn': ORIGIN, 'secret': 'private'}]
            raise error
        return ToolMessage(content=await research(context, fail, ORIGIN, is_fetch=True), tool_call_id=call['id'])
    result = json.loads((await tool_node(context, request, operation)).content)
    assert 'links' not in result and 'failedUrl' not in result and not result['sourceDiscovered']
    async with context.sessions() as db:
        saved = (await db.get(Job, context.job_id)).result
        metadata = json.dumps(saved.get('webReadFailures'))
        assert 'private' not in metadata and '127.0.0.1' not in metadata and not saved.get('webSources')


async def test_retry_failure_target_tracks_the_last_actual_attempt_and_recovers(setup, fast_nodes):
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'changing-redirect-input')
    origins, calls = [], []
    def response(request):
        url = str(request.url)
        calls.append(url)
        if url == ORIGIN:
            origins.append(url)
            return httpx.Response(301, headers={'location': TARGET + str(len(origins))})
        raise httpx.ReadTimeout('controlled timeout', request=request)
    transport = httpx.MockTransport(response)
    call = {'name': 'web_fetch', 'args': {'url': ORIGIN}, 'id': 'changing-redirect', 'type': 'tool_call'}
    request = SimpleNamespace(tool_call=call, state={'messages': [AIMessage(id='changing', content='', tool_calls=[call])]})
    async def operation():
        return ToolMessage(content=await research(context, lambda value: web_research.web_fetch(value, transport=transport), ORIGIN, is_fetch=True), tool_call_id=call['id'], name='web_fetch')
    first = await tool_node(context, request, operation)
    result = json.loads(first.content)
    assert result['failedUrl'] == TARGET + '2' and len(result['links']) == 2
    assert calls == [ORIGIN, TARGET + '1', ORIGIN, TARGET + '2']
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        state = execution(job)
        node = state['nodes'][-1]
        node.pop('output')
        assert job.result['webReadFailures'][node['id']]['failedUrl'] == TARGET + '2'
        assert job.result['webSources'][ORIGIN]['redirectTo'] == TARGET + '2'
        assert job.result['webSources'][ORIGIN]['fetchState'] == 'redirected'
        save(job, state)
    restored = await tool_node(context, request, operation)
    assert restored.content == first.content and len(calls) == 4
