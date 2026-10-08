"""Real incremental model IO and authorized snapshots on isolated fixture tenants."""
import asyncio
import hashlib
import json
import random
from datetime import timedelta
import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.agent.runtime.reply_stream import JsonStringPrefix, ReplyCandidate
from app.db.base import now
from app.integrations.models.stream_events import ModelDelta, ToolDelta
from app.integrations.models.transport import ProviderError
from app.modules.messages.models import Message
from app.tasks.context import LostLease
from app.tasks.feedback.feedback import events, snapshot, publish
from app.tasks.feedback.reply_stream import ReplyPublisher, presentation_text
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from test_business_actions import runtime
from test_company import send, keyed
from test_model_services import create, route
from test_model_stream_errors import client_for, stream
from fakes import wire_completion

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('seed', range(12))
async def test_json_lexer_handles_every_split_and_arbitrary_field_order(seed):
    answer = '# 中文😀\n[链接](https://example.org)\n```json\n{"q": "引号\\反斜线"}\n```\n|甲|乙|\n|---|---|'
    data = {'before': [1, True, None, {'answer': '不展示'}], 'answer': answer, 'after': {'nested': [False, -2.3e4]}}
    if seed % 2:
        data = dict(reversed(list(data.items())))
    raw = json.dumps(data, ensure_ascii=seed % 3 != 0)
    parser = JsonStringPrefix('answer')
    rng = random.Random(seed)
    offset, previous = 0, ''
    while offset < len(raw):
        size = 1 if seed == 0 else rng.randint(1, 11)
        text = parser.feed(raw[offset:offset + size])
        assert answer.startswith(text) and text.startswith(previous)
        assert not any(0xD800 <= ord(c) <= 0xDFFF for c in text)
        offset, previous = offset + size, text
    assert parser.finish()['answer'] == answer == parser.text


@pytest.mark.parametrize('raw', [
    '{"answer":"safe","answer":"unsafe"}', '{"answer":"safe","nested":{"a":1,"a":2}}',
    '{"answer":123}', '{"answer":"bad\\q"}', '{"answer":"\\ud800x"}',
    '{"answer":"\\udc00"}', '{"answer":"bad\n"}', '{"answer":"ok",}',
    '{"answer":"ok","other":[true,]}', '{"answer":"ok"}{}', '{"answer":"unfinished',
])
async def test_json_lexer_rejects_ambiguous_or_damaged_parameters(raw):
    parser = JsonStringPrefix('answer')
    with pytest.raises(ValueError):
        for char in raw:
            parser.feed(char)
        parser.finish()


async def test_json_lexer_keeps_nesting_bound_without_capping_answer_length():
    with pytest.raises(ValueError):
        JsonStringPrefix('answer').feed('{"other":' + '[' * 65)
    parser = JsonStringPrefix('answer')
    parser.feed('{"answer":""}')
    assert parser.finish() == {'answer': ''}


class CapturingPublisher:
    def __init__(self):
        self.values = []
    async def write(self, text, **options):
        self.values.append(text)
    async def withdraw(self):
        self.values.append(None)


async def test_candidate_selects_only_answer_and_retracts_late_mixed_tools():
    publisher = CapturingPublisher()
    candidate = ReplyCandidate(publisher)
    await candidate.feed(ModelDelta('内部过程', (ToolDelta(0, 'finish_', '{"answer":"你好'),)))
    assert not publisher.values
    await candidate.feed(ModelDelta('更多内部过程', (ToolDelta(0, 'task', '世界"}'),)))
    assert publisher.values == ['你好世界']
    await candidate.finish()
    with pytest.raises(ProviderError):
        await candidate.feed(ModelDelta(tools=(ToolDelta(1, 'read_document', '{}'),)))
    assert publisher.values[-1] is None
    other = ReplyCandidate(CapturingPublisher())
    await other.feed(ModelDelta('普通工具伴随文字', (ToolDelta(0, 'web_search', '{"query":"内部查询"}'),)))
    await other.finish()
    assert other.publisher.values == []


async def test_preview_keeps_markdown_and_holds_only_internal_citations():
    assert presentation_text('[公开](https://example.org) <b>文字</b> {"k":1}') == '[公开](https://example.org) <b>文字</b> {"k":1}'
    for marker in ('[[file:secret]]', '[[business:secret]]'):
        for end in range(1, len(marker)):
            assert 'secret' not in presentation_text('说明' + marker[:end])
        assert presentation_text('说明' + marker + '继续') == '说明（来源待核对）继续'


def packet(arguments, *, first=False, finish=None):
    call = {'index': 0, 'function': {'arguments': arguments}}
    if first:
        call.update(id='answer-call', type='function')
        call['function']['name'] = 'finish_task'
    return ('data: ' + json.dumps({'choices': [{'delta': {'content': '不可显示的伴随内容', 'tool_calls': [call]}, 'finish_reason': finish}]}) + '\n\n').encode()


class PausedStream(httpx.AsyncByteStream):
    def __init__(self, answer):
        raw = wire_completion(answer)['tool_calls'][0]['function']['arguments']
        self.chunks = [raw[:20], raw[20:35], raw[35:]]
        self.arrived = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
        self.release = [asyncio.Event(), asyncio.Event(), asyncio.Event()]
        self.done = False
    async def __aiter__(self):
        for i, chunk in enumerate(self.chunks):
            yield packet(chunk, first=i == 0)
            self.arrived[i].set()
            await self.release[i].wait()
        yield b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n'
        self.done = True
    def unblock(self):
        for gate in self.release:
            gate.set()


@pytest.mark.parametrize('scenario', ['chat', 'search', 'document', 'protocol', 'search_protocol'])
async def test_live_prefixes_reach_sse_before_provider_finishes_and_final_is_saved(setup, monkeypatch, scenario):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=route(saved))).status_code == 200
    answer = '# 你好，正在生成中文回答。\n\n这是一段公开或本人可见的完整分析。'
    upstream = PausedStream(answer)
    requests, searches = [], []
    async def search(query, *, domains=None):
        assert domains is None
        searches.append(query)
        return {'query': query, 'items': [{'title': '公开资料', 'url': 'https://example.org', 'snippet': '公开摘要'}]}
    monkeypatch.setattr('app.integrations.web_research.web_search', search)
    def response(request):
        requests.append(json.loads(request.content))
        if scenario.startswith('search') and len(requests) == 1:
            return stream({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'search', 'function': {'name': 'web_search', 'arguments': '{"query":"公开资料"}'}}]}, 'finish_reason': 'tool_calls'}]})
        if scenario.endswith('protocol') and len(requests) == (2 if scenario.startswith('search') else 1):
            return stream({'choices': [{'delta': {'content': answer}, 'finish_reason': 'stop'}]})
        return httpx.Response(200, stream=upstream, headers={'Content-Type': 'text/event-stream'})
    client_for(monkeypatch, response)
    if scenario == 'document':
        from test_documents import upload
        attachment = await upload(clients['employee'], '本人材料.txt', '本人的文本材料'.encode(), 'text/plain')
        sent = (await clients['employee'].post('/api/v1/messages', json={'text': '解释材料', 'attachmentIds': [attachment['id']]}, headers=keyed())).json()
    else:
        sent = await send(clients['employee'], '解释一段公开内容')
    token = hashlib.sha256(clients['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        task = asyncio.create_task(process_job(await claim(sessions, users['employee'].id), sessions, settings, saver))
        received = events(sessions, token, sent['jobId'])
        try:
            await asyncio.wait_for(upstream.arrived[0].wait(), 10)
            first = json.loads((await asyncio.wait_for(anext(received), 1)).split('data: ', 1)[1])
            assert first['replyStream']['text'] and not upstream.done
            assert first['replyStream']['state'] == 'streaming'
            # HTTP stream is still paused; it cannot have delivered a final reply.
            detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
            assert detail['replyStream'] == first['replyStream'] and detail['reply'] == ''
            await asyncio.sleep(.21)
            upstream.release[0].set()
            await asyncio.wait_for(upstream.arrived[1].wait(), 5)
            second = json.loads((await anext(received)).split('data: ', 1)[1])
            assert second['replyStream']['text'].startswith(first['replyStream']['text'])
            assert len(second['replyStream']['text']) > len(first['replyStream']['text']) and not upstream.done
            assert '不可显示' not in json.dumps(second, ensure_ascii=False)
        finally:
            upstream.unblock()
            await task
            await received.aclose()
    detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['state'] in ('succeeded', 'awaiting_input'), detail
    assert answer in detail['reply'] and not detail['replyStream']
    assert len(requests) == 1 + int(scenario.startswith('search')) + int(scenario.endswith('protocol'))
    assert len(searches) == int(scenario.startswith('search'))
    if scenario.endswith('protocol'):
        assert [tool['function']['name'] for tool in requests[-1]['tools']] == ['finish_task']
        assert requests[-1]['tool_choice'] == {'type': 'function', 'function': {'name': 'finish_task'}}
        async with sessions() as db:
            job = await db.get(Job, sent['jobId'])
            assert job.result['deliveryRepairs'] == ['protocol'] and not job.result.get('toolOutcomes')
        assert not detail['actions'] and not detail['drafts']
    terminal = await snapshot(sessions, token, sent['jobId'])
    assert terminal['state'] == detail['job']['state'] and terminal['replyStream'] is None


@pytest.mark.parametrize('boundary', [
    'references', 'completion', 'reference_then_protocol', 'protocol_reference_loop',
    'semantic_then_protocol', 'unforced_protocol', 'team', 'review',
])
async def test_corrective_and_private_model_calls_stay_buffered(setup, monkeypatch, boundary):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from app.agent.runtime.model import BoundedChatModel
    from app.agent.tools.completion import finish_task
    from fakes import completion
    who = 'admin' if boundary == 'team' else 'employee'
    context, sent = await runtime(setup, '说明已有结果', who=who)
    async def resolve(*args):
        return {'baseUrl': 'https://example.org/v1', 'model': 'controlled', 'streaming': True, 'parameters': {}}, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    messages = [HumanMessage(id=f'job:{context.job_id}', content='说明已有结果'), AIMessage(content='已有普通正文')]
    protocol = HumanMessage(id=f'delivery-repair:{context.job_id}', content='仅包装已有正文')
    semantic = HumanMessage(id=f'completion-repair:{context.job_id}', content='修正遗漏操作')
    invalid = completion('引用有误的正文', operation_ids=['unknown-receipt'])
    error = ToolMessage(tool_call_id=invalid.tool_calls[0]['id'], name='finish_task', status='error',
                        content='引用校验未通过', additional_kwargs={'completion_reference_error': True})
    if boundary in ('references', 'completion'):
        messages.append(HumanMessage(id=f'delivery-references:{context.job_id}', content='纠正引用') if boundary == 'references' else semantic)
    elif boundary == 'reference_then_protocol':
        messages.extend([invalid, error, AIMessage(content='错误后的纯文字'), protocol])
    elif boundary == 'protocol_reference_loop':
        messages.extend([protocol, invalid, error])
    elif boundary == 'semantic_then_protocol':
        messages.extend([semantic, AIMessage(content='修正过程中的纯文字'), protocol])
    elif boundary == 'unforced_protocol':
        messages.append(protocol)
    elif boundary == 'team':
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.access = {**job.access, 'team': True}
    model = BoundedChatModel(model='controlled', api_key='unused', max_retries=0, streaming=False,
                             use_responses_api=False, stream_usage=False)
    model._run_context = context
    model._verification = boundary == 'review'
    bound = model.bind_tools([finish_task], **({} if boundary == 'unforced_protocol' else {'tool_choice': 'finish_task'}))
    answer = '这段内部修正必须完整校验后才能显示，不能从模型分片提前发布。'
    upstream = PausedStream(answer)
    client_for(monkeypatch, lambda _: httpx.Response(200, stream=upstream, headers={'Content-Type': 'text/event-stream'}))
    task = asyncio.create_task(bound.ainvoke(messages))
    try:
        await asyncio.wait_for(upstream.arrived[0].wait(), 10)
        for index in range(2):
            feedback = (await setup[3][who].get(f"/api/v1/jobs/{sent['jobId']}/feedback")).json()
            assert not (feedback.get('replyStream') or {}).get('text') and not upstream.done
            upstream.release[index].set()
            await asyncio.wait_for(upstream.arrived[index + 1].wait(), 5)
    finally:
        upstream.unblock()
        result = await task
    assert result.tool_calls[0]['args']['answer'] == answer and context.calls == 1


async def test_publisher_throttles_preserves_phases_and_cancel_fences_late_writes(setup):
    context, sent = await runtime(setup, '普通聊天')
    publisher = ReplyPublisher(context, 'call')
    await publisher.start()
    await publisher.write('第一段')
    async with context.sessions() as db:
        before = (await db.get(Job, context.job_id)).feedback['seq']
    for i in range(30):
        await publisher.write('第一段' + str(i))
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).feedback['seq'] == before
    await publish(context, 'reviewing', force=True)
    client = setup[3]['employee']
    value = (await client.get(f"/api/v1/jobs/{sent['jobId']}/feedback")).json()
    assert value['replyStream']['text'] == '第一段' and value['stage'] == 'reviewing'
    cancelled = await client.post(f"/api/v1/jobs/{sent['jobId']}/cancel", json={'expectedAttempt': 0, 'expectedFence': context.fence})
    assert cancelled.status_code == 200
    assert cancelled.json()['replyStream'] == {**value['replyStream'], 'state': 'interrupted'}
    for role in ('peer', 'outsider'):
        forbidden = await setup[3][role].post(f"/api/v1/jobs/{sent['jobId']}/cancel", json={'expectedAttempt': 0, 'expectedFence': context.fence})
        assert forbidden.status_code == 404 and '第一段' not in forbidden.text
    with pytest.raises(LostLease):
        await publisher.write('迟到内容', force=True)
    value = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert value['replyStream']['state'] == 'interrupted' and value['replyStream']['text'] == '第一段'
    assert not value['reply']
    async with context.sessions() as db:
        result = (await db.get(Job, context.job_id)).result
        assert 'conversationReply' not in result


@pytest.mark.parametrize('failure,expected', [('network', 'interrupted'), ('content_filter', 'withdrawn'), ('invalid_response', 'withdrawn')])
async def test_failure_retention_and_manual_retry_replace_in_place(setup, failure, expected):
    context, sent = await runtime(setup, '普通聊天')
    publisher = ReplyPublisher(context, 'call')
    await publisher.start()
    await publisher.write('可以保留的片段')
    await publisher.fail(ProviderError(failure, '受控故障'), '可以保留的片段和末尾')
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state, job.lease_until = 'awaiting_retry', None
    client = setup[3]['employee']
    value = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert value['replyStream']['state'] == expected
    assert value['replyStream']['text'] == ('可以保留的片段和末尾' if expected == 'interrupted' else '')
    generation = value['replyStream']['generation']
    assert (await client.post(f"/api/v1/jobs/{sent['jobId']}/retry", json={})).status_code == 200
    retried = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert retried['id'] == sent['messageId'] and retried['replyStream']['text'] == ''
    assert retried['replyStream']['generation'] > generation


@pytest.mark.parametrize('change', ['team', 'role', 'transcript', 'deleted', 'logout', 'owner'])
async def test_preview_never_survives_authorization_or_source_changes(setup, change):
    context, sent = await runtime(setup, '普通聊天')
    publisher = ReplyPublisher(context, 'call')
    await publisher.start()
    await publisher.write('私有片段')
    client = setup[3]['employee']
    if change == 'logout':
        await client.post('/api/v1/auth/logout')
    elif change == 'owner':
        client = setup[3]['peer']
    else:
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            message = await db.get(Message, sent['messageId'])
            if change == 'team':
                job.access = {**job.access, 'team': True}
            elif change == 'role':
                from app.modules.members.models import Member
                (await db.get(Member, context.owner_id)).role = 'admin'
            elif change == 'transcript':
                message.transcript_revision += 1
            elif change == 'deleted':
                message.deleted = True
    response = await client.get(f"/api/v1/jobs/{sent['jobId']}/feedback")
    assert '私有片段' not in response.text
    detail = await client.get('/api/v1/messages/' + sent['messageId'])
    assert '私有片段' not in detail.text


async def test_expired_worker_seals_prefix_and_old_fence_cannot_write(setup):
    context, sent = await runtime(setup, '普通聊天')
    publisher = ReplyPublisher(context, 'call')
    await publisher.start()
    await publisher.write('中断前的片段')
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.lease_until = now() - timedelta(seconds=1)
        job.request_started = True
    await claim(context.sessions, context.owner_id)
    with pytest.raises(LostLease):
        await publisher.write('旧worker', force=True)
    value = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert value['replyStream']['state'] == 'interrupted'
    assert value['replyStream']['text'] == '中断前的片段'


async def test_team_prefixes_do_not_write_per_token(setup):
    context, _ = await runtime(setup, '普通聊天', who='admin')
    publisher = ReplyPublisher(context, 'call')
    await publisher.start()
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.access = {**job.access, 'team': True}
    await publisher.write('团队资料')
    async with context.sessions() as db:
        before = (await db.get(Job, context.job_id)).feedback['seq']
    for i in range(50):
        await publisher.write('团队资料' + str(i))
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.feedback['seq'] == before and job.feedback['replyStream']['text'] == ''


from test_task_retry import fast_nodes  # shared deterministic retry clock


@pytest.mark.parametrize('ending,count,state', [('network', 4, 'interrupted'), ('content_filter', 1, 'withdrawn'), ('invalid_response', 4, 'withdrawn')])
async def test_upstream_failure_after_real_prefix_never_executes_incomplete_completion(setup, monkeypatch, fast_nodes, ending, count, state):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    await clients['admin'].put('/api/v1/settings/model-routing', json=route(saved))
    attempts, prefixes = [], []
    original = ReplyPublisher.write
    async def observed(self, text, **kwargs):
        await original(self, text, **kwargs)
        if text and kwargs.get('state', 'streaming') == 'streaming':
            prefixes.append(text)
    monkeypatch.setattr(ReplyPublisher, 'write', observed)
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            arguments = wire_completion('尚未完成的正文')['tool_calls'][0]['function']['arguments']
            if ending == 'invalid_response':
                arguments = arguments[:-1] + ',"answer":"重复字段"}'
            yield packet(arguments[:20], first=True)
            if ending == 'network':
                raise httpx.ReadError('controlled disconnect')
            yield packet(arguments[20:])
            yield ('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'content_filter' if ending == 'content_filter' else 'tool_calls'}]}) + '\n\ndata: [DONE]\n\n').encode()
    def response(request):
        attempts.append(True)
        return httpx.Response(200, stream=BrokenStream())
    client_for(monkeypatch, response)
    sent = await send(clients['employee'], '解释概念')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(await claim(sessions, users['employee'].id), sessions, settings, saver)
    detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert prefixes and len(attempts) == count
    assert detail['replyStream']['state'] == state
    assert bool(detail['replyStream']['text']) == (state == 'interrupted')
    assert detail['reply'] == '' and not detail['actions'] and not detail['drafts']
    assert detail['job']['state'] == 'awaiting_retry'
    generations = detail['replyStream']['generation']
    assert generations >= count
    async with sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert 'pendingReply' not in job.result and 'conversationReply' not in job.result


async def test_streamed_answer_finishes_without_contacting_unavailable_judge(setup, monkeypatch, fast_nodes):
    settings, sessions, users, clients = setup
    saved = await create(clients['admin'])
    await clients['admin'].put('/api/v1/settings/model-routing', json=route(saved))
    answer = '已整理这段方案，可以继续完善内容。'
    arguments = wire_completion(answer, business=False)['tool_calls'][0]['function']['arguments']
    client_for(monkeypatch, lambda _: httpx.Response(200, content=packet(arguments, first=True, finish='tool_calls') + b'data: [DONE]\n\n'))
    class UnavailableReview:
        async def ainvoke(self, messages):
            raise ProviderError('network', '受控核对断网')
    sent = await send(clients['employee'], '说明方案')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(await claim(sessions, users['employee'].id), sessions, settings, saver, reply_model=UnavailableReview())
    detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['taskOutcome']['state'] == 'completed'
    assert detail['reply'] == answer
    assert not any(node['kind'] == 'review' for node in detail['job']['nodes'])
