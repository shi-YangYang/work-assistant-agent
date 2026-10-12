import asyncio
import time
import pytest
from app.tasks.streaming.publisher import ReplyPublisher
from app.tasks.streaming.protocol import MAX_SNAPSHOT_BYTES
from app.tasks.models import Job
from _support.agent.business_actions import runtime

pytestmark = pytest.mark.asyncio


async def test_slow_authorization_and_redis_never_block_upstream_or_create_token_tasks(setup, monkeypatch):
    context, _ = await runtime(setup, '受控长回复')
    publisher = ReplyPublisher(context, 'slow')
    original = publisher._publish
    entered = asyncio.Event()
    async def slow(text, state):
        entered.set()
        await asyncio.sleep(.2)
        await original(text, state)
    monkeypatch.setattr(publisher, '_publish', slow)
    await publisher.start()
    from sqlalchemy import event
    statements = []
    engine = context.sessions.kw['bind'].sync_engine
    def observed(connection, cursor, statement, parameters, execution_context, executemany):
        if statement.lstrip().upper().startswith('UPDATE'):
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', observed)
    await publisher.write('开头')
    await entered.wait()
    started = time.monotonic()
    for i in range(2000):
        await publisher.write('中文😀' * (i + 1))
    elapsed = time.monotonic() - started
    assert elapsed < .2
    assert len([task for task in asyncio.all_tasks() if task.get_name() == 'reply:slow']) == 1
    assert publisher.pending[0] == '中文😀' * 2000
    await publisher.flush()
    event.remove(engine, 'before_cursor_execute', observed)
    assert not statements
    print('controlled_publisher', {'input_chunks': 2000, 'producer_ms': round(elapsed * 1000, 3), 'body_updates': len(statements)})
    assert publisher.task.done() and publisher.text == '中文😀' * 2000
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.feedback['replyStream']['text'] == ''
        assert '中文' not in str(job.feedback)
    assert (await publisher.store.snapshot(publisher.identity))['text'] == publisher.text


async def test_preview_capacity_and_redis_failure_do_not_cap_final_candidate(setup, monkeypatch):
    context, _ = await runtime(setup, '受控长回复')
    publisher = ReplyPublisher(context, 'capacity')
    await publisher.start()
    text = 'x' * (MAX_SNAPSHOT_BYTES + 100)
    await publisher.write(text)
    assert publisher.pending == ('', 'unavailable') and publisher.disabled
    await publisher.flush()
    assert len(text) > MAX_SNAPSHOT_BYTES
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.feedback['replyStream']['state'] == 'unavailable'
        assert job.feedback['replyStream']['text'] == ''


async def test_withdrawal_cancels_slow_pending_publish_and_cannot_reappear(setup, monkeypatch):
    context, _ = await runtime(setup, '取消不会重现旧内容')
    publisher = ReplyPublisher(context, 'withdraw')
    started = asyncio.Event()
    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(publisher, '_publish', blocked)
    await publisher.start()
    await publisher.write('禁止保留')
    await started.wait()
    await publisher.withdraw()
    assert publisher.task.done() and publisher.text == '' and publisher.pending is None
    assert (await publisher.store.snapshot(publisher.identity))['sealed']
    await publisher.write('迟到内容')
    assert publisher.pending is None
    await publisher.close()


async def test_shutdown_persists_authorized_partial_and_terminal_snapshot_wins(setup, monkeypatch):
    import hashlib
    from app.tasks.processing import handlers
    from app.tasks.feedback.feedback import snapshot
    from app.tasks.feedback.reply_stream import temporary_snapshot
    context, sent = await runtime(setup, '停机前已确认权限的片段')
    published = asyncio.Event()
    saved = {}
    async def running(active, *args, **kwargs):
        publisher = ReplyPublisher(active, 'shutdown')
        await publisher.start()
        await publisher.write('停机前已确认权限的片段')
        await publisher.drain()
        saved['publisher'] = publisher
        saved['snapshot'] = await publisher.store.snapshot(publisher.identity)
        published.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(handlers, '_execute_job', running)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    task = asyncio.create_task(handlers.process_job(job, context.sessions, context.settings, None))
    await asyncio.wait_for(published.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with context.sessions.begin() as db:
        live = await db.get(Job, context.job_id)
        assert live.feedback['replyStream']['text'] == '停机前已确认权限的片段'
        assert live.feedback['replyStream']['state'] == 'interrupted'
        live.state = 'awaiting_retry'
    assert saved['publisher'].task.done()
    assert (await temporary_snapshot(context.settings, job))['closed']
    token = hashlib.sha256(setup[3]['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    value = await snapshot(context.sessions, token, sent['jobId'], temporary=saved['snapshot'])
    assert value['state'] == 'awaiting_retry'
    assert value['replyStream']['text'] == '停机前已确认权限的片段'


@pytest.mark.parametrize('failures', [1, 2])
async def test_final_database_retry_never_replays_model_or_announces_false_success(setup, monkeypatch, failures):
    from app.tasks.processing import handlers
    from sqlalchemy.exc import OperationalError
    from _support.agent.response_delivery import run, model
    original, attempts = handlers.verified_citations, []
    async def persist(*args, **kwargs):
        attempts.append(1)
        if len(attempts) <= failures:
            raise OperationalError(None, None, RuntimeError('controlled database outage'))
        return await original(*args, **kwargs)
    monkeypatch.setattr(handlers, 'verified_citations', persist)
    fake = model(answer='完整最终正文')
    result, _ = await run(setup, fake)
    assert fake.calls == 1 and len(attempts) == 2
    if failures == 1:
        assert result['reply'] == '完整最终正文' and result['job']['state'] == 'awaiting_input'
    else:
        assert result['reply'] == '' and result['job']['state'] == 'failed'


async def test_v2_delta_new_subscriber_and_idle_source_revocation(setup):
    import hashlib
    import json
    from app.tasks.feedback.feedback import events
    from app.modules.messages.models import Message
    context, sent = await runtime(setup, '有权限的受控流')
    token = hashlib.sha256(setup[3]['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    publisher = ReplyPublisher(context, 'sse')
    await publisher.start()
    first = events(context.sessions, token, context.job_id, settings=context.settings, version=2)
    async def next_type(source, wanted):
        async with asyncio.timeout(2):
            async for raw in source:
                if raw.startswith('event: ' + wanted):
                    return json.loads(raw.split('data: ', 1)[1])
    try:
        await next_type(first, 'snapshot')
        started = time.monotonic()
        await publisher.write('中文😀')
        await publisher.drain()
        sync = await next_type(first, 'reply_sync')
        elapsed = time.monotonic() - started
        assert elapsed < 1
        print('controlled_candidate_to_sse', {'elapsed_ms': round(elapsed * 1000, 3)})
        assert sync['text'] == '中文😀' and 'nodes' not in sync
        await publisher.write('中文😀后半段')
        await publisher.drain()
        delta = await next_type(first, 'reply_delta')
        assert delta['delta'] == '后半段' and 'text' not in delta and 'nodes' not in delta
        second = events(context.sessions, token, context.job_id, settings=context.settings, version=2)
        recovered = await next_type(second, 'reply_sync')
        assert recovered['text'] == '中文😀后半段' and recovered['seq'] == delta['seq']
        await second.aclose()
        async with context.sessions.begin() as db:
            message = await db.get(Message, sent['messageId'])
            message.transcript_revision += 1
        withdrawn = await next_type(first, 'reply_withdrawn')
        assert withdrawn['state'] == 'withdrawn'
        assert (await publisher.store.snapshot(publisher.identity))['text'] == ''
    finally:
        await first.aclose()
        await publisher.close()


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('revocation', ['idle_source', 'new_snapshot_source', 'sealed', 'generation'])
async def test_all_withdrawals_reach_negotiated_client_protocol(setup, version, revocation):
    import hashlib
    import json
    from app.tasks.feedback.feedback import events
    from app.modules.messages.models import Message
    context, sent = await runtime(setup, '撤回必须立即清除已展示正文')
    token = hashlib.sha256(setup[3]['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    publisher = ReplyPublisher(context, 'withdraw-protocol')
    await publisher.start()
    await publisher.write('即将撤回的正文')
    await publisher.drain()
    source = events(context.sessions, token, context.job_id, settings=context.settings, version=version)
    async def next_reply(state):
        async with asyncio.timeout(2):
            async for raw in source:
                if not raw.startswith('event: '):
                    continue
                name = raw.split('\n', 1)[0].removeprefix('event: ')
                # Match exactly the events understood by the negotiated client.
                if version == 1:
                    assert name in ('snapshot', 'unavailable')
                value = json.loads(raw.split('data: ', 1)[1])
                reply = value.get('replyStream') if name == 'snapshot' else value
                if reply and reply.get('state') == state:
                    return reply
    try:
        if revocation != 'new_snapshot_source':
            initial = await next_reply('streaming')
            assert initial['text'] == '即将撤回的正文'
        if revocation in ('idle_source', 'new_snapshot_source'):
            async with context.sessions.begin() as db:
                message = await db.get(Message, sent['messageId'])
                message.transcript_revision += 1
        elif revocation == 'sealed':
            await publisher.store.seal(publisher.identity)
        else:
            async with context.sessions.begin() as db:
                job = await db.get(Job, context.job_id)
                job.feedback = {**job.feedback, 'replyStream': {
                    **job.feedback['replyStream'], 'generation': publisher.generation + 1}}
        withdrawn = await next_reply('withdrawn')
        assert not withdrawn.get('text')
        assert withdrawn['generation'] == publisher.generation + (revocation == 'generation')
        if revocation != 'generation':
            assert (await publisher.store.snapshot(publisher.identity))['text'] == ''
    finally:
        await source.aclose()
        await publisher.close()


async def test_final_and_interruption_database_failures_preserve_prefix(setup, monkeypatch):
    import hashlib
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from sqlalchemy.exc import OperationalError
    from app.tasks.processing import handlers
    from app.tasks.feedback.feedback import snapshot
    from app.tasks.runtime.queue import claim
    from app.modules.messages.models import Message
    from _support.agent.response_delivery import model
    from _support.http.company import send
    settings, sessions, users, clients = setup
    sent = await send(clients['employee'], '数据库保存故障不能主动销毁正文')
    job = await claim(sessions, users['employee'].id)
    fake = model(answer='仍可恢复的已授权正文')
    original = handlers.invoke_harness
    saved, attempts = {}, []
    async def invoke(context, *args, **kwargs):
        answer = await original(context, *args, **kwargs)
        publisher = ReplyPublisher(context, 'failed-final-save')
        await publisher.start()
        await publisher.write(answer, state='finalizing')
        await publisher.flush()
        saved['publisher'] = publisher
        saved['snapshot'] = await publisher.store.snapshot(publisher.identity)
        for key in publisher.store.keys(publisher.identity):
            await publisher.store.client.pexpire(key, 60000)
        return answer
    async def fail_final(*args, **kwargs):
        attempts.append('final')
        raise OperationalError(None, None, RuntimeError('controlled final save outage'))
    async def fail_recovery(*args, **kwargs):
        attempts.append('interruption')
        raise OperationalError(None, None, RuntimeError('controlled interruption save outage'))
    monkeypatch.setattr(handlers, 'invoke_harness', invoke)
    monkeypatch.setattr(handlers, 'verified_citations', fail_final)
    monkeypatch.setattr(handlers, 'interrupt_usage', fail_recovery)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        with pytest.raises(OperationalError):
            await handlers.process_job(job, sessions, settings, saver, model=fake)
    assert attempts == ['final', 'final', 'interruption'] and fake.calls == 1
    publisher = saved['publisher']
    assert publisher.closed and publisher.task.done()
    current = await publisher.store.snapshot(publisher.identity)
    assert current == {**saved['snapshot'], 'closed': True}
    assert 0 < await publisher.store.client.pttl(publisher.store.keys(publisher.identity)[0]) <= 60000
    await publisher.write('迟到分片')
    assert publisher.pending is None
    for generation in (publisher.generation, publisher.generation + 1):
        assert not await publisher.store.publish(publisher.identity, {
            **current, 'generation': generation, 'seq': current['seq'] + 1, 'text': '迟到写入'}, {'seq': current['seq'] + 1})
    async with sessions() as db:
        live = await db.get(Job, job.id)
        message = await db.get(Message, sent['messageId'])
        assert live.state == 'running' and message.reply == ''
        assert live.feedback['replyStream']['text'] == ''
    token = hashlib.sha256(clients['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    recovered = await snapshot(sessions, token, job.id, temporary=current)
    assert recovered['state'] == 'running'
    assert recovered['replyStream']['text'] == fake.answer
    # Retaining a failed save never grants access after a later source change.
    async with sessions.begin() as db:
        message = await db.get(Message, sent['messageId'])
        message.transcript_revision += 1
    revoked = await snapshot(sessions, token, job.id, temporary=current)
    assert revoked['replyStream']['state'] == 'withdrawn' and revoked['replyStream']['text'] == ''


async def test_source_revocation_still_clears_prefix_when_recovery_database_fails(setup, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.tasks.context import InputChanged
    from app.tasks.processing import handlers
    context, _ = await runtime(setup, '失效资料不得因数据库故障保留')
    saved = {}
    async def execute(active, *args, **kwargs):
        publisher = ReplyPublisher(active, 'revoked-save')
        await publisher.start()
        await publisher.write('失效正文')
        await publisher.drain()
        saved['publisher'] = publisher
        raise InputChanged()
    async def fail_recovery(*args, **kwargs):
        raise OperationalError(None, None, RuntimeError('controlled recovery outage'))
    monkeypatch.setattr(handlers, '_execute_job', execute)
    monkeypatch.setattr(handlers, 'interrupt_usage', fail_recovery)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    with pytest.raises(OperationalError):
        await handlers.process_job(job, context.sessions, context.settings, None)
    publisher = saved['publisher']
    assert publisher.closed and publisher.task.done()
    current = await publisher.store.snapshot(publisher.identity)
    assert current['closed'] and current['sealed'] and current['text'] == ''
