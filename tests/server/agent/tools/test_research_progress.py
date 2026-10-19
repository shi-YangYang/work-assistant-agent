"""Research reuses evidence without treating query changes as discoveries."""
import copy
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.runtime.model import BoundedChatModel
from app.agent.runtime.tool_nodes import tool_node
from app.agent.runtime.tool_progress import begin, end
from app.agent.runtime.tool_progress.evidence import request_key, result_key, web_address
from app.core.digests import digest
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from _support.agent.business_actions import runtime


def hit(url, snippet='事实摘要'):
    return {'url': url, 'title': url, 'snippet': snippet, 'evidenceType': 'search_snippet'}


def test_search_identity_uses_evidence_not_query_or_ranking():
    first = {'name': 'web_search', 'args': {'query': 'first'}}
    second = {'name': 'web_search', 'args': {'query': 'other wording'}}
    a, b = hit('https://example.org/a'), hit('https://example.org/b')
    assert result_key(first, {'query': 'first', 'items': [a, b]}) == result_key(second, {'query': 'other wording', 'items': [b, a]})
    assert result_key(first, {'items': [a]}) != result_key(first, {'items': [{**a, 'snippet': '新事实'}]})


@pytest.mark.parametrize('call', [
    {'name': 'web_search', 'args': {'query': None, 'domains': ['example.org', 1]}},
    {'name': 'web_fetch', 'args': {'url': None}},
    {'name': 'web_fetch', 'args': {'url': 'https://[invalid'}},
])
def test_progress_normalization_leaves_invalid_arguments_to_tool_validation(call):
    assert isinstance(request_key(call), str)
    assert web_address(call) is None or isinstance(web_address(call), str)


def test_failed_address_identity_normalizes_authority_without_merging_distinct_paths():
    def key(url):
        return web_address({'name': 'web_fetch', 'args': {'url': url}})
    assert key('https://EXAMPLE.org:443#one') == key('https://example.org/#two')
    assert key('https://example.org/a%2Fb') != key('https://example.org/a/b')
    assert key('https://example.org/page?q=one') != key('https://example.org/page?q=two')


@pytest.mark.asyncio
async def test_changed_queries_with_only_known_excerpts_warn_without_hard_stall(setup):
    context, _ = await runtime(setup)
    a, b = hit('https://example.org/a'), hit('https://example.org/b')
    for index, items in enumerate(([a, b], [b], [a, b], [a, {**b, 'snippet': '新事实'}])):
        call = {'name': 'web_search', 'args': {'query': f'query {index}'}, 'id': str(index)}
        assert await begin(context, call) is None
        result = await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'query': f'query {index}', 'items': items})))
        payload = json.loads(result.content)
        assert payload['newEvidenceCount'] == (2, 0, 0, 1)[index]
        assert payload['items'] == items
        assert ('progressNotice' in payload) == (index in (1, 2))
        if index in (1, 2):
            assert payload['progressNotice'] == '本次搜索没有新增来源或摘要，已有结果仍有效。'
        assert not {'remaining', 'completed', 'blocked', 'nextStep'}.intersection(payload)
        async with context.sessions() as db:
            state = (await db.get(Job, context.job_id)).result['toolProgress']
            assert state['stalled'] == 0
            assert bool(state['calls'][-1].get('softStall')) == (index in (1, 2))
            assert not state['stopped']


@pytest.mark.asyncio
@pytest.mark.parametrize('name,args,content,expected', [
    ('web_search', {'query': 'new'}, {'items': [hit('https://example.org/new')]},
     {'newEvidenceCount': 1}),
    ('web_search', {'query': 'same evidence'}, {'items': [hit('https://example.org/known')]},
     {'newEvidenceCount': 0, 'progressNotice': '本次搜索没有新增来源或摘要，已有结果仍有效。'}),
    ('web_fetch', {'url': 'https://example.org/denied'}, {'state': 'unavailable', 'errorCode': 'http_403'},
     {'progressNotice': '本次未取得网页正文，已有来源仍有效。'}),
    ('web_fetch', {'url': 'https://example.org/read'}, {'text': '正文', 'nextOffset': 100}, {}),
    ('web_fetch', {'url': 'https://example.org/known'}, {'state': 'unavailable', 'errorCode': 'http_403',
     'sourceDiscovered': True, 'evidenceLevel': 'search_snippet', 'availableEvidence': hit('https://example.org/known')},
     {'progressNotice': '本次未取得网页正文，已有来源仍有效。'}),
])
async def test_web_node_replay_preserves_feedback_and_model_identity_without_recounting(setup, name, args, content, expected):
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'research-replay')
    seed = {'name': 'web_search', 'args': {'query': 'seed'}, 'id': 'seed'}
    assert await begin(context, seed) is None
    await end(context, seed, ToolMessage(tool_call_id='seed', content=json.dumps({
        'items': [hit('https://example.org/known')]})))
    call = {'name': name, 'args': args, 'id': 'original', 'type': 'tool_call'}
    batch = AIMessage(id='batch', content='', tool_calls=[call])
    request = SimpleNamespace(tool_call=call, state={'messages': [batch]})
    progress_call = {**call, 'progressId': digest({'message': batch.id, 'call': call['id']})}
    executions = []
    async def operation():
        executions.append(True)
        return ToolMessage(id='original-output', name=name, tool_call_id=call['id'], content=json.dumps(content))
    assert await begin(context, progress_call) is None
    original_node_output = await tool_node(context, request, operation)
    first = await end(context, progress_call, original_node_output)
    assert json.loads(first.content) == {**content, **expected}

    # Later evidence must not turn the original count into zero on recovery.
    later = {'name': 'web_search', 'args': {'query': 'later'}, 'id': 'later'}
    assert await begin(context, later) is None
    await end(context, later, ToolMessage(tool_call_id='later', content=json.dumps({
        'items': [hit('https://example.org/later')]})))
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']
    assert next(row for row in journal['calls'] if row['id'] == progress_call['progressId'])['webFeedback'] == expected

    assert await begin(context, progress_call) is None
    restored_node_output = await tool_node(context, request, operation)
    assert restored_node_output.model_dump() == original_node_output.model_dump()
    replayed = await end(context, progress_call, restored_node_output)
    assert replayed.model_dump() == first.model_dump() and executions == [True]
    model = BoundedChatModel(model='controlled-no-network', api_key='test')
    def model_identity(receipt):
        messages = [HumanMessage(id='question', content='查找资料'), batch, receipt]
        return digest({'request': model._get_request_payload(messages), 'binding': context.model_binding,
                       'messages': [message.id for message in messages]})
    assert model_identity(first) == model_identity(replayed)
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['toolProgress'] == journal

    # Old journals did not store derived feedback. Do not invent it from the
    # current evidence set or mutate counters while restoring the raw receipt.
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        legacy = copy.deepcopy(job.result['toolProgress'])
        next(row for row in legacy['calls'] if row['id'] == progress_call['progressId']).pop('webFeedback')
        job.result = {**job.result, 'toolProgress': legacy}
    assert await begin(context, progress_call) is None
    legacy_replay = await end(context, progress_call, await tool_node(context, request, operation))
    assert legacy_replay.model_dump() == original_node_output.model_dump() and executions == [True]
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['toolProgress'] == legacy


@pytest.mark.asyncio
async def test_distinct_low_gain_searches_close_only_research_after_six_no_progress_results(setup):
    """Replay the six request/result shapes that forced T09-low to finalize.

    Excerpts are synthetic unit inputs, not replacement model answers. Real
    provider revalidation is recorded separately from this boundary regression.
    """
    context, _ = await runtime(setup)
    known = [hit(f'https://example.org/result-{index}') for index in range(5)]
    seed = {'name': 'web_search', 'args': {'query': 'OpenAI products'}, 'id': 'seed'}
    assert await begin(context, seed) is None
    await end(context, seed, ToolMessage(tool_call_id='seed', content=json.dumps({'items': known})))
    attempts = [
        ('web_search', {'query': 'site:openai.com ChatGPT', 'domains': ['openai.com']}, {'items': []}),
        ('web_fetch', {'url': 'https://openai.com/chatgpt/overview/'}, {'state': 'unavailable', 'errorCode': 'http_403'}),
        ('web_fetch', {'url': 'https://chatgpt.com/'}, {'state': 'unavailable', 'errorCode': 'web_network'}),
        ('web_search', {'query': 'OpenAI Sora official page openai.com'}, {'items': known}),
        ('web_search', {'query': 'openai.com ChatGPT 介绍 官方页面'}, {'items': known}),
        ('web_fetch', {'url': 'https://openai.com/index/chatgpt/'}, {'state': 'unavailable', 'errorCode': 'http_403'}),
    ]
    for index, (name, args, content) in enumerate(attempts):
        call = {'name': name, 'args': args, 'id': f'actual-pattern-{index}'}
        assert await begin(context, call) is None
        result = await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps(content)))
        assert 'progressNotice' in json.loads(result.content)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['toolProgress']['stalled'] == 0
        assert not job.result['toolProgress']['stopped']
        assert job.result.get('taskBudget', {}).get('phase') != 'finalizing'
    targeted = {'name': 'web_search', 'args': {'query': 'chatgpt.com ChatGPT 官方 网页版 介绍',
                                            'domains': ['chatgpt.com']}, 'id': 'new-source'}
    assert json.loads((await begin(context, targeted)).content)['code'] == 'research_no_progress'
    assert await begin(context, {'name': 'find_documents', 'args': {}, 'id': 'read-private'}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('name,args,content', [
    ('web_search', {'query': 'same'}, {'items': []}),
    ('web_fetch', {'url': 'https://example.org/denied'}, {'state': 'unavailable', 'errorCode': 'http_403'}),
])
async def test_six_repeated_research_requests_still_stop_without_refetch(setup, name, args, content):
    context, _ = await runtime(setup)
    call = {'name': name, 'args': args, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id='first', content=json.dumps(content)))
    for index in range(6):
        assert await begin(context, {**call, 'id': f'repeated-{index}'})
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        journal = job.result['toolProgress']
        assert journal['stalled'] == 0 and not journal['stopped']
        assert journal['research']['stopped']
        assert sum(row.get('executed') is True for row in journal['calls']) == 1
        assert job.result.get('taskBudget', {}).get('reason') != 'no_progress'


@pytest.mark.asyncio
async def test_same_address_transient_retries_remain_bounded(setup):
    context, _ = await runtime(setup)
    for index in range(6):
        call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/temporary', 'find': str(index)},
                'id': str(index)}
        assert await begin(context, call) is None
        await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({
            'state': 'unavailable', 'errorCode': 'web_network'})))
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']
        assert journal['calls'][0]['softStall']
        assert journal['stalled'] == 0 and not journal['stopped']
    assert json.loads((await begin(context, {**call, 'id': 'seventh'})).content)['code'] == 'research_no_progress'


@pytest.mark.asyncio
async def test_invalid_search_arguments_do_not_become_soft_exploration(setup):
    context, _ = await runtime(setup)
    for index in range(6):
        call = {'name': 'web_search', 'args': {'query': index}, 'id': str(index)}
        assert await begin(context, call) is None
        await end(context, call, ToolMessage(tool_call_id=call['id'], status='error', content=json.dumps({
            'state': 'failed', 'category': 'invalid_arguments'})))
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']
        assert journal['stalled'] == 0 and not journal['stopped']
    assert json.loads((await begin(context, {**call, 'id': 'seventh'})).content)['code'] == 'research_no_progress'


def test_soft_stall_preserves_prior_hard_stalls_instead_of_claiming_progress():
    from app.agent.runtime.tool_progress import state
    journal = {**state.create('scope'), 'stalled': 3, 'seen': ['existing-result']}
    journal, _ = state.admit(journal, 'new-query', 'different-request', 'deps')
    journal, warning = state.complete(journal, 'new-query', 'existing-result', 'deps', soft_stall=True)
    assert warning and journal['stalled'] == 3 and not journal['stopped']
    assert journal['calls'][-1]['softStall']


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['http_401', 'http_403', 'blocked_url', 'web_challenge'])
async def test_same_page_denial_cannot_be_refreshed_but_new_url_and_scope_are_allowed(setup, code):
    from dataclasses import replace
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/denied#one'}, 'id': 'denied'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'state': 'unavailable', 'errorCode': code})))
    assert await begin(context, {**call, 'id': 'same', 'args': {'url': 'https://example.org/denied#two', 'find': 'new'}})
    refresh = {**call, 'id': 'refresh', 'args': {**call['args'], 'refresh': True}}
    assert await begin(context, refresh)
    assert await begin(context, {**call, 'id': 'other', 'args': {'url': 'https://example.org/other'}}) is None
    assert await begin(replace(context, node_scope='new-user-input'), refresh) is None


@pytest.mark.asyncio
async def test_legacy_denial_without_failure_classification_keeps_refresh_behavior(setup):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/denied'}, 'id': 'denied'}
    assert await begin(context, call) is None
    message = ToolMessage(tool_call_id=call['id'], content='{"state":"unavailable","errorCode":"http_403"}')
    await end(context, call, message)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        result = copy.deepcopy(job.result)
        result['toolProgress']['calls'][-1].pop('readError')
        result['toolProgress'].pop('research')
        job.result = result
    # Restoring an old receipt must not retrofit its classification or decisions.
    await end(context, call, message)
    async with context.sessions() as db:
        assert 'readError' not in (await db.get(Job, context.job_id)).result['toolProgress']['calls'][-1]
    assert await begin(context, {**call, 'id': 'refresh', 'args': {**call['args'], 'refresh': True}}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['web_network', 'http_429', 'http_503'])
async def test_transient_failure_can_recover_with_same_request(setup, code):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/page'}, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'state': 'unavailable', 'errorCode': code})))
    assert await begin(context, {**call, 'id': 'recover'}) is None


@pytest.mark.asyncio
async def test_exhausted_network_failure_cannot_be_reopened_by_model_refresh(setup):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/page#first'}, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id='first', content=json.dumps({
        'state': 'unavailable', 'errorCode': 'web_network', 'attemptsExhausted': True})))
    assert await begin(context, {**call, 'id': 'same-page', 'args': {
        'url': 'https://example.org/page#second', 'find': 'a new phrase'}})
    assert await begin(context, {**call, 'id': 'another-page', 'args': {'url': 'https://example.org/other'}}) is None
    refresh = {**call, 'id': 'explicit-refresh', 'args': {**call['args'], 'refresh': True}}
    assert await begin(context, refresh)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert not job.result['toolProgress']['stopped']
        assert job.result.get('taskBudget', {}).get('phase') != 'finalizing'


@pytest.mark.asyncio
async def test_repeated_empty_document_discovery_requires_changed_source_state(setup):
    from app.modules.conversations.models import ConversationContext
    context, sent = await runtime(setup)
    call = {'name': 'find_documents', 'args': {'query': '不存在'}, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], content='{"items":[],"nextOffset":null}'))
    assert await begin(context, {**call, 'id': 'repeated'})
    async with context.sessions.begin() as db:
        source = await db.get(ConversationContext, sent['conversationId'])
        if source is None:
            source = ConversationContext(conversation_id=sent['conversationId'], company_id=context.company_id,
                                         owner_id=context.owner_id, invalidation_version=1)
            db.add(source)
        else:
            source.invalidation_version += 1
        context.context_sources['invalidationVersion'] = source.invalidation_version
    assert await begin(context, {**call, 'id': 'changed-source'}) is None
