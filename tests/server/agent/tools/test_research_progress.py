"""Research reuses evidence without treating query changes as discoveries."""
import json

import pytest
from langchain_core.messages import ToolMessage

from app.agent.runtime.tool_progress import begin, end
from app.agent.runtime.tool_progress.evidence import request_key, result_key, web_address
from app.tasks.models import Job
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


@pytest.mark.asyncio
async def test_changed_queries_with_only_known_excerpts_warn_without_hard_stall(setup):
    context, _ = await runtime(setup)
    a, b = hit('https://example.org/a'), hit('https://example.org/b')
    for index, items in enumerate(([a, b], [b], [a, b], [a, {**b, 'snippet': '新事实'}])):
        call = {'name': 'web_search', 'args': {'query': f'query {index}'}, 'id': str(index)}
        assert await begin(context, call) is None
        result = await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'query': f'query {index}', 'items': items})))
        assert ('progressNotice' in json.loads(result.content)) == (index in (1, 2))
        if index in (1, 2):
            notice = json.loads(result.content)['progressNotice']
            assert '不代表任务完成或失败' in notice
            assert '对照用户原请求与已有依据' in notice and '否则只查尚缺的用户要求' in notice
        async with context.sessions() as db:
            state = (await db.get(Job, context.job_id)).result['toolProgress']
            assert state['stalled'] == 0
            assert bool(state['calls'][-1].get('softStall')) == (index in (1, 2))
            assert not state['stopped']


@pytest.mark.asyncio
async def test_t09_distinct_low_gain_searches_and_new_url_failures_leave_sources_available(setup):
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
    assert await begin(context, targeted) is None
    result = await end(context, targeted, ToolMessage(tool_call_id='new-source', content=json.dumps({
        'items': [hit('https://learn.chatgpt.com/docs')]})))
    assert 'progressNotice' not in json.loads(result.content)


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
        assert journal['stalled'] == 6 and journal['stopped']
        assert sum(row.get('executed') is True for row in journal['calls']) == 1
        assert job.result['taskBudget']['reason'] == 'no_progress'


@pytest.mark.asyncio
async def test_same_address_transient_retries_remain_bounded(setup):
    context, _ = await runtime(setup)
    for index in range(7):
        call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/temporary', 'find': str(index)},
                'id': str(index)}
        assert await begin(context, call) is None
        await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({
            'state': 'unavailable', 'errorCode': 'web_network'})))
    async with context.sessions() as db:
        journal = (await db.get(Job, context.job_id)).result['toolProgress']
        assert journal['calls'][0]['softStall']
        assert journal['stalled'] == 6 and journal['stopped']


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
        assert journal['stalled'] == 6 and journal['stopped']


def test_soft_stall_preserves_prior_hard_stalls_instead_of_claiming_progress():
    from app.agent.runtime.tool_progress import state
    journal = {**state.create('scope'), 'stalled': 3, 'seen': ['existing-result']}
    journal, _ = state.admit(journal, 'new-query', 'different-request', 'deps')
    journal, warning = state.complete(journal, 'new-query', 'existing-result', 'deps', soft_stall=True)
    assert warning and journal['stalled'] == 3 and not journal['stopped']
    assert journal['calls'][-1]['softStall']


@pytest.mark.asyncio
async def test_same_page_denial_is_not_refetched_but_new_url_and_refresh_are_allowed(setup):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/denied#one'}, 'id': 'denied'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'state': 'unavailable', 'errorCode': 'http_403'})))
    assert await begin(context, {**call, 'id': 'same', 'args': {'url': 'https://example.org/denied#two', 'find': 'new'}})
    assert await begin(context, {**call, 'id': 'refresh', 'args': {**call['args'], 'refresh': True}}) is None
    assert await begin(context, {**call, 'id': 'other', 'args': {'url': 'https://example.org/other'}}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['web_network', 'http_429', 'http_503'])
async def test_transient_failure_can_recover_with_same_request(setup, code):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/page'}, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'state': 'unavailable', 'errorCode': code})))
    assert await begin(context, {**call, 'id': 'recover'}) is None


@pytest.mark.asyncio
async def test_exhausted_network_failure_reused_by_address_until_explicit_refresh(setup):
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.org/page#first'}, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id='first', content=json.dumps({
        'state': 'unavailable', 'errorCode': 'web_network', 'attemptsExhausted': True})))
    assert await begin(context, {**call, 'id': 'same-page', 'args': {
        'url': 'https://example.org/page#second', 'find': 'a new phrase'}})
    assert await begin(context, {**call, 'id': 'another-page', 'args': {'url': 'https://example.org/other'}}) is None
    refresh = {**call, 'id': 'explicit-refresh', 'args': {**call['args'], 'refresh': True}}
    assert await begin(context, refresh) is None
    await end(context, refresh, ToolMessage(tool_call_id=refresh['id'], content=json.dumps({
        'url': 'https://example.org/page', 'text': 'A real first passage', 'nextOffset': 3000})))
    assert await begin(context, {**call, 'id': 'next-passage', 'args': {
        'url': 'https://example.org/page', 'offset': 3000}}) is None
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
