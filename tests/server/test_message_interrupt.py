"""User interruption, admission races and resource cleanup on the dedicated test DB."""
import asyncio
import hashlib
import time
from datetime import timedelta
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import func, select
from app.db.base import now
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import ConversationContext
from app.modules.messages.models import Message
from app.modules.model_services.models import ModelUsage
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks import cancellation, handlers, node_execution
from app.tasks.context import LostLease, RunContext
from app.tasks.lease import lease
from app.tasks.models import Job
from app.tasks.queue import claim
from test_business_actions import runtime
from test_company import keyed, send

pytestmark = pytest.mark.asyncio


async def cancel(client, job_id, *, attempt=0, fence=0):
    return await client.post(f'/api/v1/jobs/{job_id}/cancel', json={
        'expectedAttempt': attempt, 'expectedFence': fence,
    })


async def test_concurrent_send_idempotency_and_conversation_scope(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    headers = keyed()
    body = {'text': '第一条请求', 'attachmentIds': []}
    responses = await asyncio.gather(*[client.post('/api/v1/messages', json=body, headers=headers) for _ in range(2)])
    assert [r.status_code for r in responses] == [202, 202]
    first = responses[0].json()
    assert responses[1].json() == first
    blocked = await client.post('/api/v1/messages', json={'text': '并发请求'}, headers=keyed())
    assert blocked.status_code == 409 and blocked.json()['error']['code'] == 'conversation_busy'
    active = await client.get(f"/api/v1/conversations/{first['conversationId']}/active-job")
    assert active.json()['job']['id'] == first['jobId']
    other = await client.post('/api/v1/messages', json={'text': '另一个会话', 'newConversation': True}, headers=keyed())
    assert other.status_code == 202
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Message).where(Message.owner_id == users['employee'].id)) == 2
    await cancel(client, first['jobId'])
    attempts = await asyncio.gather(*[client.post('/api/v1/messages', json={'text': f'竞争 {i}', 'conversationId': first['conversationId']}, headers=keyed()) for i in range(2)])
    assert sorted(r.status_code for r in attempts) == [202, 409]


async def test_send_and_old_retry_compete_for_one_conversation(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    old = await send(client)
    async with sessions.begin() as db:
        (await db.get(Job, old['jobId'])).state = 'failed'
    results = await asyncio.gather(
        client.post('/api/v1/messages', json={'text': '新请求'}, headers=keyed()),
        client.post(f"/api/v1/jobs/{old['jobId']}/retry", json={}),
    )
    assert sorted(r.status_code for r in results) in ([200, 409], [202, 409])
    refused = next(r for r in results if r.status_code == 409)
    assert refused.json()['error']['code'] == 'conversation_busy'


async def test_cancel_queue_is_idempotent_and_preserves_source_and_completed_nodes(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    sent = await send(client, '保留原始内容')
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.feedback = {'seq': 8, 'text': '未经核对的流式内容', 'stage': 'generating'}
        job.result = {'pendingReply': {'answer': '不得进入上下文'}, 'nodeExecution': {'scope': 'test', 'nodes': [
            {'id': state, 'scope': 'test', 'kind': 'model', 'label': state, 'state': state, 'attempts': 1, 'nextAt': time.time() + 10}
            for state in ('succeeded', 'running', 'retry_wait', 'waiting')
        ]}}
    response = await cancel(client, sent['jobId'])
    assert response.status_code == 200
    value = response.json()
    assert value['state'] == 'cancelled' and value['fence'] == 1
    assert [row['state'] for row in value['nodes']] == ['succeeded', 'cancelled', 'cancelled', 'cancelled']
    assert all(row['nextRetryAt'] is None and not row['canRetry'] for row in value['nodes'])
    assert (await cancel(client, sent['jobId'])).json() == value
    assert await claim(sessions, users['employee'].id) is None
    assert (await client.get(f"/api/v1/conversations/{sent['conversationId']}/active-job")).json() == {'job': None}
    async with sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert job.feedback['seq'] > 8 and job.feedback['text'] == ''
        assert 'pendingReply' not in job.result and job.lease_until is None
        message = await db.get(Message, sent['messageId'])
        assert message.text == '保留原始内容' and not message.deleted and not message.reply
    assert (await client.post('/api/v1/messages', json={'text': '下一条'}, headers=keyed())).status_code == 202


async def test_cancel_permission_kind_and_execution_version(setup):
    _, sessions, users, clients = setup
    sent = await send(clients['employee'])
    for who in ('peer', 'outsider', 'admin'):
        assert (await cancel(clients[who], sent['jobId'])).status_code == 404
        assert (await clients[who].get(f"/api/v1/conversations/{sent['conversationId']}/active-job")).status_code == 404
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state, job.attempt = 'failed', 1
        report = Job(owner_id=job.owner_id, company_id=job.company_id, kind='report', target_id=uuid4().hex)
        db.add(report)
        await db.flush()
        report_id = report.id
    assert (await cancel(clients['employee'], report_id)).status_code == 409
    assert (await clients['employee'].post(f"/api/v1/jobs/{sent['jobId']}/retry", json={})).status_code == 200
    stale = await cancel(clients['employee'], sent['jobId'])
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'job_version_changed'
    assert (await cancel(clients['employee'], sent['jobId'], attempt=2)).json()['state'] == 'cancelled'
    async with sessions() as db:
        assert (await db.get(Job, report_id)).state == 'queued'


async def test_completed_and_revoked_jobs_return_truth(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    sent = await send(client)
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state, job.phase = 'succeeded', 'complete'
    assert (await cancel(client, sent['jobId'])).json()['state'] == 'succeeded'
    next_sent = await send(client)
    async with sessions.begin() as db:
        job = await db.get(Job, next_sent['jobId'])
        job.access = {**job.access, 'team': True, 'invalidated': True}
    assert (await cancel(client, next_sent['jobId'])).status_code == 403
    assert (await client.get(f"/api/v1/conversations/{sent['conversationId']}/active-job")).status_code == 403


async def test_legacy_queue_selects_running_then_keeps_waiting_messages(setup):
    _, sessions, users, clients = setup
    sent = await send(clients['employee'])
    running = await claim(sessions, users['employee'].id)
    async with sessions.begin() as db:
        message = Message(owner_id=running.owner_id, company_id=running.company_id, conversation_id=sent['conversationId'], text='旧客户端已排队')
        db.add(message)
        await db.flush()
        queued = Job(owner_id=running.owner_id, company_id=running.company_id, kind='message', target_id=message.id, created_at=running.created_at - timedelta(seconds=1))
        db.add(queued)
        await db.flush()
        queued_id = queued.id
    url = f"/api/v1/conversations/{sent['conversationId']}/active-job"
    assert (await clients['employee'].get(url)).json()['job']['id'] == running.id
    await cancel(clients['employee'], running.id, fence=running.fence)
    assert (await clients['employee'].get(url)).json()['job']['id'] == queued_id
    assert (await clients['employee'].post('/api/v1/messages', json={'text': '仍不能发送'}, headers=keyed())).status_code == 409


async def test_cancel_preserves_committed_actions_independent_report_and_context(setup):
    from app.agent.operations import execute
    from app.modules.conversations.context_store import publish_summary
    context, sent = await runtime(setup, '帮我创建工作报价方案，再生成日报')
    work = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    report = await execute(context, step=2, action='generate_report', report_date=now().date().isoformat())
    assert work['state'] == 'succeeded' and report['state'] == 'running'
    async with context.sessions.begin() as db:
        store = await db.get(ConversationContext, sent['conversationId'])
        store.payload = {**store.payload, 'summary': '已核对的既有内容'}
        db.add(ModelUsage(company_id=context.company_id, owner_id=context.owner_id, job_id=context.job_id, kind='assistant', job_attempt=0, job_fence=context.fence, status='running', started_at=now()))
    assert (await cancel(setup[3]['employee'], context.job_id, fence=context.fence)).status_code == 200
    with pytest.raises(LostLease):
        await execute(context, step=3, action='create_work', changes={'title': '迟到操作'})
    with pytest.raises(LostLease):
        await publish_summary(context, {'summary': '迟到的压缩结果'})
    with pytest.raises(LostLease):
        async with context.sessions.begin() as db:
            await lease(db, context)
    async with context.sessions() as db:
        assert (await db.get(WorkItem, work['objectId'])).title == '报价方案'
        assert (await db.get(Job, report['job']['id'])).state == 'queued'
        rows = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == sent['messageId']).order_by(BusinessAction.step))).all()
        assert [row.state for row in rows] == ['succeeded', 'running']
        assert (await db.get(ConversationContext, sent['conversationId'])).payload['summary'] == '已核对的既有内容'
        assert (await db.scalar(select(ModelUsage).where(ModelUsage.job_id == context.job_id))).status == 'unknown'


@pytest.mark.parametrize('stage', ['model', 'tool', 'compaction', 'retry_wait', 'review'])
async def test_running_pipeline_cancels_wait_and_cannot_finish(setup, monkeypatch, stage):
    from app.integrations.models.transport import ProviderError
    settings, sessions, users, clients = setup
    entered, cleaned = asyncio.Event(), asyncio.Event()
    calls = []
    async def blocked():
        calls.append(True)
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaned.set()
    async def harness(context, *args, **kwargs):
        if stage == 'review':
            return '等待核对的答案'
        if stage == 'retry_wait':
            async def transient():
                calls.append(True)
                raise ProviderError('timeout', 'controlled timeout')
            async def sleep(delay):
                entered.set()
                try:
                    await asyncio.Future()
                finally:
                    cleaned.set()
            real_run = node_execution.run
            async def retry_run(*args, **kwargs):
                return await real_run(*args, **kwargs, wait=sleep)
            monkeypatch.setattr(node_execution, 'run', retry_run)
            return await node_execution.execute_node(context, identity='blocked', kind='model', label='思考中', operation=transient)
        return await node_execution.execute_node(context, identity='blocked', kind=stage, label='处理中', operation=blocked)
    async def review(*args, **kwargs):
        await blocked()
    monkeypatch.setattr(handlers, 'invoke_harness', harness)
    monkeypatch.setattr('app.agent.reply_review.review_reply', review)
    sent = await send(clients['employee'])
    job = await claim(sessions, users['employee'].id)
    task = asyncio.create_task(handlers.process_job(job, sessions, settings, None, model=object()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        started = time.monotonic()
        response = await cancel(clients['employee'], job.id, fence=job.fence)
        assert response.status_code == 200
        await asyncio.wait_for(task, 3)
        assert time.monotonic() - started < 3 and cleaned.is_set() and len(calls) == 1
        async with sessions() as db:
            saved = await db.get(Job, job.id)
            assert saved.state == 'cancelled' and saved.fence > job.fence
            assert 'pendingReply' not in saved.result
            assert not (await db.get(Message, sent['messageId'])).reply
        assert await claim(sessions, users['employee'].id) is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancellation_closes_waiting_http_stream(setup, monkeypatch):
    settings, sessions, users, clients = setup
    entered, disconnected = asyncio.Event(), asyncio.Event()
    async def serve(reader, writer):
        try:
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n')
            await writer.drain()
            entered.set()
            await reader.read()
            disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    async def harness(*args, **kwargs):
        async with httpx.AsyncClient() as client:
            async with client.stream('GET', f'http://127.0.0.1:{port}/', timeout=None) as stream:
                async for _ in stream.aiter_text():
                    pass
    monkeypatch.setattr(handlers, 'invoke_harness', harness)
    await send(clients['employee'])
    job = await claim(sessions, users['employee'].id)
    task = asyncio.create_task(handlers.process_job(job, sessions, settings, None, model=object()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await cancel(clients['employee'], job.id, fence=job.fence)
        await asyncio.wait_for(task, 3)
        await asyncio.wait_for(disconnected.wait(), 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()


async def test_parsing_cancel_reaps_child_and_clears_attachment_processing(setup, monkeypatch, tmp_path):
    from app.integrations.parsing.process import parse_process
    settings, sessions, users, clients = setup
    marker = tmp_path / 'parser-started'
    script = tmp_path / 'slow-parser.py'
    script.write_text('import time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("started")\ntime.sleep(60)\n')
    data = b'controlled original document'
    async with sessions.begin() as db:
        actor = users['employee']
        attachment = Attachment(company_id=actor.company_id, owner_id=actor.id, kind='document', mime='text/plain', name='original.txt', size=len(data), sha256=hashlib.sha256(data).hexdigest())
        db.add(attachment)
        await db.flush()
        identifier = attachment.id
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / identifier).write_bytes(data)
    children = []
    create = asyncio.create_subprocess_exec
    async def tracked(*args, **kwargs):
        process = await create(*args, **kwargs)
        if str(script) in args:
            children.append(process)
        return process
    async def parser(path, suffix):
        return await parse_process(path, suffix, entrypoint=script)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', tracked)
    monkeypatch.setattr('app.tasks.documents.parse_process', parser)
    sent = await send(clients['employee'], attachments=[identifier])
    job = await claim(sessions, users['employee'].id)
    task = asyncio.create_task(handlers.process_job(job, sessions, settings, None, model=object()))
    try:
        async def wait_started():
            while not marker.exists():
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait_started(), 5)
        assert (await cancel(clients['employee'], job.id, fence=job.fence)).status_code == 200
        await asyncio.wait_for(task, 3)
        assert len(children) == 1 and children[0].returncode is not None
        async with sessions() as db:
            document = await db.get(Attachment, identifier)
            assert document.extraction_status == 'failed' and '已中断' in document.extraction_info['error']
            assert not document.deleted and document.message_id == sent['messageId']
        assert (settings.media_dir / identifier).read_bytes() == data
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_heartbeat_failure_stops_execution_and_records_failure(setup, monkeypatch):
    settings, sessions, users, clients = setup
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def harness(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaned.set()
    async def broken_heartbeat(context):
        await entered.wait()
        raise ValueError('账号权限已变化，请重新提问；旧处理已停止')
    monkeypatch.setattr(handlers, 'invoke_harness', harness)
    monkeypatch.setattr(cancellation, 'heartbeat', broken_heartbeat)
    await send(clients['employee'])
    job = await claim(sessions, users['employee'].id)
    await asyncio.wait_for(handlers.process_job(job, sessions, settings, None, model=object()), 5)
    assert cleaned.is_set()
    async with sessions() as db:
        saved = await db.get(Job, job.id)
        assert saved.state == 'cancelled' and saved.lease_until is None


async def test_transcription_cancel_keeps_original_audio_without_late_transcript(setup):
    settings, sessions, users, clients = setup
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async with sessions.begin() as db:
        actor = users['employee']
        attachment = Attachment(company_id=actor.company_id, owner_id=actor.id, kind='audio', mime='audio/wav', name='original.wav', size=8, sha256='controlled')
        db.add(attachment)
        await db.flush()
        identifier = attachment.id
    async def provider(context, audio):
        assert audio.id == identifier
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cleaned.set()
    sent = await send(clients['employee'], attachments=[identifier])
    job = await claim(sessions, users['employee'].id)
    task = asyncio.create_task(handlers.process_job(job, sessions, settings, None, model=object(), asr_provider=provider))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await cancel(clients['employee'], job.id, fence=job.fence)
        await asyncio.wait_for(task, 3)
        assert cleaned.is_set()
        async with sessions() as db:
            audio = await db.get(Attachment, identifier)
            assert not audio.deleted and audio.message_id == sent['messageId']
            assert not (await db.get(Message, sent['messageId'])).transcript
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_completion_and_cancel_race_has_single_terminal_winner(setup):
    settings, sessions, users, clients = setup
    sent = await send(clients['employee'])
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings)
    async def finish():
        try:
            async with sessions.begin() as db:
                current, _ = await lease(db, context)
                message = await db.get(Message, sent['messageId'])
                message.reply = '已核对的最终答案'
                current.state, current.lease_until = 'succeeded', None
        except LostLease:
            pass
    response, _ = await asyncio.gather(cancel(clients['employee'], job.id, fence=job.fence), finish())
    assert response.status_code == 200 and response.json()['state'] in ('succeeded', 'cancelled')
    async with sessions() as db:
        current = await db.get(Job, job.id)
        message = await db.get(Message, sent['messageId'])
        assert current.state == response.json()['state']
        assert bool(message.reply) == (current.state == 'succeeded')
