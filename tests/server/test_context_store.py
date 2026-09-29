import pytest
from uuid import uuid4
from sqlalchemy import event, select
from app.agent.context.conversation_context import conversation_references
from app.db.base import now
from app.modules.conversations.context.context_store import publish_summary
from app.modules.conversations.context.context_invalidation import invalidate
from app.modules.conversations.models import ConversationContext
from app.modules.messages.models import Message
from app.tasks.context import RunContext, InputChanged
from app.tasks.runtime.queue import claim

pytestmark = pytest.mark.asyncio


async def sent(client, text, conversation=None):
    body = {'text': text}
    if conversation:
        body['conversationId'] = conversation
    response = await client.post('/api/v1/messages', json=body, headers={'Idempotency-Key': uuid4().hex})
    assert response.status_code == 202, response.text
    return response.json()


async def legacy_message(sessions, actor, text, conversation):
    # Historical queued messages remain readable, although new requests can no
    # longer enqueue a second active message through the public API.
    async with sessions.begin() as db:
        item = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation, text=text)
        db.add(item)
        await db.flush()
        return {'messageId': item.id, 'conversationId': conversation}


async def test_snapshot_incremental_history_order_and_owner_isolation(setup, monkeypatch):
    settings, sessions, users, clients = setup
    first = await sent(clients['employee'], '第一条')
    second = await legacy_message(sessions, users['employee'], '第二条', first['conversationId'])
    actor = users['employee']
    job = await claim(sessions, actor.id)
    async with sessions.begin() as db:
        current = await db.get(Message, first['messageId'])
        assert await conversation_references(db, actor, job, current) == []  # Future request never leaks backwards.
    async with sessions.begin() as db:
        current = await db.get(Message, second['messageId'])
        refs = await conversation_references(db, actor, job, current)
        assert [r['userText'] for r in refs] == ['第一条']
    async def should_not_rebuild(*args, **kwargs):
        raise AssertionError('Unchanged history unexpectedly rebuilt')
    monkeypatch.setattr('app.modules.conversations.references.message_reference', should_not_rebuild)
    async with sessions.begin() as db:
        current = await db.get(Message, second['messageId'])
        assert len(await conversation_references(db, actor, job, current)) == 1
        store = await db.get(ConversationContext, first['conversationId'])
        assert store.payload['recentMessages'][0]['id'] == first['messageId']
    for role in ('peer', 'outsider'):
        assert (await clients[role].get('/api/v1/conversations/' + first['conversationId'] + '/context-usage')).status_code == 404
    assert (await clients['employee'].get('/api/v1/conversations/' + first['conversationId'] + '/context-usage')).json() == {'contextUsage': None}


async def test_late_reply_revision_replaces_cached_reference(setup):
    settings, sessions, users, clients = setup
    first = await sent(clients['employee'], '原问题')
    second = await legacy_message(sessions, users['employee'], '后续', first['conversationId'])
    actor = users['employee']; job = await claim(sessions, actor.id)
    async with sessions.begin() as db:
        current = await db.get(Message, second['messageId'])
        await conversation_references(db, actor, job, current)
    async with sessions.begin() as db:
        previous = await db.get(Message, first['messageId']); previous.reply = '稍后完成的回答'
    async with sessions.begin() as db:
        current = await db.get(Message, second['messageId'])
        refs = await conversation_references(db, actor, job, current)
        assert refs[0]['assistantReference'] == '稍后完成的回答'
        assert len(refs) == 1


async def test_invalidated_summary_cannot_publish_and_original_remains(setup):
    from app.modules.conversations.context.context_store import capture_sources
    settings, sessions, users, clients = setup
    first = await sent(clients['employee'], '原始问题')
    actor = users['employee']; job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    async with sessions.begin() as db:
        current = await db.get(Message, first['messageId'])
        await conversation_references(db, actor, job, current)
        sources = await capture_sources(db, actor, current)
    async with sessions.begin() as db:
        await invalidate(db, conversation_id=first['conversationId'])
    with pytest.raises(InputChanged, match='对话引用的资料已变化'):
        await publish_summary(context, {'id': 'old', 'summary': '失效摘要', 'covered': [], 'sources': sources})
    async with sessions() as db:
        assert (await db.get(Message, first['messageId'])).text == '原始问题'
        assert (await db.get(ConversationContext, first['conversationId'])).payload == {}


async def test_tool_summary_keeps_its_own_access_after_failed_job(setup):
    from app.modules.conversations.context.context_store import capture_sources
    from app.modules.members.models import Member
    from app.security.access import scope
    from app.tasks.models import Job
    settings, sessions, users, clients = setup
    actor = users['admin']; first = await sent(clients['admin'], '查询员工资料')
    job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    access = {**scope(actor), 'team': True, 'reads': {'controlled-source': {'type': 'member', 'id': users['employee'].id, 'ownerId': users['employee'].id}}}
    async with sessions.begin() as db:
        live = await db.get(Job, job.id); live.access = access
        current = await db.get(Message, first['messageId'])
        await conversation_references(db, actor, live, current)
        sources = await capture_sources(db, actor, current)
    await publish_summary(context, {'id': 'tool-summary', 'summary': '员工私密资料', 'covered': [], 'sources': sources, 'access': access})
    async with sessions.begin() as db:
        live = await db.get(Job, job.id); live.state = 'failed'
        changed = await db.get(Member, actor.id); changed.role = 'employee'
        current = await db.get(Message, first['messageId'])
        assert not current.access.get('team')  # The answer never committed.
    async with sessions.begin() as db:
        changed = await db.get(Member, actor.id)
        current = await db.get(Message, first['messageId'])
        refs = await conversation_references(db, changed, live, current)
        assert all('员工私密资料' not in r['assistantReference'] for r in refs)
        store = await db.get(ConversationContext, current.conversation_id)
        assert not store.payload.get('summary')


async def test_newer_tool_summary_is_not_visible_to_older_task(setup):
    from app.modules.conversations.context.context_store import capture_sources
    settings, sessions, users, clients = setup
    actor = users['employee']; first = await sent(clients['employee'], '较早问题')
    second = await legacy_message(sessions, users['employee'], '较晚的工具查询', first['conversationId'])
    job = await claim(sessions, actor.id)
    async with sessions.begin() as db:
        newer = await db.get(Message, second['messageId'])
        await conversation_references(db, actor, job, newer)
        store = await db.get(ConversationContext, first['conversationId'])
        store.payload = {**store.payload, 'summary': '后续工具读取的秘密结果', 'summarySources': {},
                         'summaryThrough': {'messageId': newer.id, 'createdAt': newer.created_at.isoformat()}}
    async with sessions.begin() as db:
        older = await db.get(Message, first['messageId'])
        assert not await conversation_references(db, actor, job, older)
        assert (await db.get(ConversationContext, first['conversationId'])).payload['summary'] == '后续工具读取的秘密结果'


async def test_lease_selects_epoch_without_context_payload(setup):
    from app.modules.conversations.context.context_store import capture_sources
    from app.tasks.lease import lease
    settings, sessions, users, clients = setup
    actor = users['employee']; first = await sent(clients['employee'], '查询')
    job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    async with sessions.begin() as db:
        current = await db.get(Message, first['messageId'])
        await conversation_references(db, actor, job, current, context=context)
    statements = []
    engine = sessions.kw['bind'].sync_engine
    def observed(conn, cursor, statement, parameters, sql_context, executemany):
        if 'company_conversation_context' in statement:
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', observed)
    try:
        async with sessions.begin() as db:
            await lease(db, context)
    finally:
        event.remove(engine, 'before_cursor_execute', observed)
    assert statements and all('.payload' not in statement for statement in statements)


async def test_checkpoint_publication_recovers_once_without_overwriting_newer_summary(setup, monkeypatch):
    from app.agent.context.checkpoints import GuardedSaver
    from app.agent.context.compaction import save_packet, saved_packet, publish_packet
    from app.modules.conversations.context.context_store import capture_sources
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    settings, sessions, users, clients = setup
    actor = users['employee']; first = await sent(clients['employee'], '需要保留的请求')
    job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    config = {'configurable': {'thread_id': f'{actor.company_id}:{actor.id}:job:{job.id}:context', 'checkpoint_ns': ''}}
    async with sessions.begin() as db:
        current = await db.get(Message, first['messageId'])
        await conversation_references(db, actor, job, current)
        sources = await capture_sources(db, actor, current)
    packet = {'id': 'recoverable', 'summary': '已压缩的原请求', 'sources': sources, 'covered': [], 'removedIds': [], 'evidence': []}
    real_publish = publish_summary
    calls = []
    async def interrupted(context, value):
        calls.append(value['id'])
        if len(calls) == 1:
            raise RuntimeError('controlled publication interruption')
        return await real_publish(context, value)
    monkeypatch.setattr('app.agent.context.compaction.publish_summary', interrupted)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        context.context_checkpoint, context.context_checkpoint_config = GuardedSaver(saver, context), config
        await save_packet(context, packet)
        with pytest.raises(RuntimeError):
            await publish_packet(context, packet)
        async with sessions() as db:
            assert not (await db.get(ConversationContext, first['conversationId'])).payload.get('summary')
        resumed = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
        resumed.context_checkpoint, resumed.context_checkpoint_config = GuardedSaver(saver, resumed), config
        recovered = await saved_packet(resumed)
        await publish_packet(resumed, recovered)
        await publish_packet(resumed, recovered)
        assert calls == ['recoverable', 'recoverable']  # Warm calls do not republish/reload history.
    async with sessions.begin() as db:
        store = await db.get(ConversationContext, first['conversationId'])
        assert store.payload['summary'] == packet['summary']
        store.payload = {**store.payload, 'summary': '更晚任务已写入', 'compactionId': 'newer',
                         'summaryThrough': {'messageId': 'newer', 'createdAt': '2099-01-01T00:00:00+00:00'}}
    with pytest.raises(InputChanged):
        await real_publish(context, packet)
    async with sessions() as db:
        assert (await db.get(ConversationContext, first['conversationId'])).payload['summary'] == '更晚任务已写入'


async def test_cold_and_incremental_query_path(setup):
    import json
    import time
    from datetime import timedelta
    settings, sessions, users, clients = setup
    actor = users['employee']; first = await sent(clients['employee'], '当前要求')
    job = await claim(sessions, actor.id)
    async with sessions.begin() as db:
        current = await db.get(Message, first['messageId'])
        for index in range(24):
            db.add(Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=current.conversation_id,
                           text=f'历史消息 {index}', reply='已核对的回复', created_at=current.created_at-timedelta(minutes=index+1)))
    engine = sessions.kw['bind'].sync_engine
    measurements = []
    for phase in ('cold', 'incremental'):
        statements = []
        def observed(conn, cursor, statement, parameters, sql_context, executemany):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', observed)
        started = time.perf_counter()
        try:
            async with sessions.begin() as db:
                current = await db.get(Message, first['messageId'])
                refs = await conversation_references(db, actor, job, current)
                assert len(refs) == 24
        finally:
            event.remove(engine, 'before_cursor_execute', observed)
        measurements.append({'phase': phase, 'queries': len(statements), 'elapsedMs': round((time.perf_counter()-started)*1000, 2)})
    assert measurements[1]['queries'] < measurements[0]['queries']
    assert measurements[1]['queries'] < 16  # Independent of all 24 historical message associations.
    print('CONTEXT_PREPARATION ' + json.dumps(measurements))


async def test_inaccessible_unselected_history_does_not_block_new_summary(setup):
    from datetime import timedelta
    from app.security.access import scope
    settings, sessions, users, clients = setup
    actor = users['admin']; sent_message = await sent(clients['admin'], '继续整理本人工作')
    job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    async with sessions.begin() as db:
        current = await db.get(Message, sent_message['messageId'])
        inaccessible = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=current.conversation_id,
            text='以前查询的员工信息', reply='现在已不可访问', created_at=current.created_at-timedelta(minutes=2),
            access={**scope(actor), 'team': True, 'reads': {'former-member': {'type': 'member', 'id': 'deleted-member', 'ownerId': 'deleted-member'}}})
        available = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=current.conversation_id,
            text='自己的计划', reply='本周整理文档', created_at=current.created_at-timedelta(minutes=1))
        db.add_all([inaccessible, available]); await db.flush()
        refs = await conversation_references(db, actor, job, current, context=context)
        assert [row['id'] for row in refs] == [available.id]
    assert inaccessible.id not in context.context_sources['sources']
    assert set(context.context_sources['sources']) == {available.id, current.id}
    await publish_summary(context, {'id': 'available-summary', 'summary': '自己的文档整理计划',
        'covered': [available.id], 'sources': context.context_sources, 'access': context.access})
    async with sessions() as db:
        assert (await db.get(ConversationContext, current.conversation_id)).payload['summary'] == '自己的文档整理计划'


async def test_other_employee_deletion_does_not_interrupt_private_file_generation(setup, monkeypatch):
    from dataclasses import replace
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from fakes import ReviewedFixtureModel, completion
    from app.modules.work.models import WorkItem
    from app.tasks.processing.handlers import process_job
    from app.tasks.models import Job
    from test_business_assistant import facts
    from test_sandbox_execution import ReceiptClient
    settings, sessions, users, clients = setup
    settings = replace(settings, sandbox_url='http://controlled-sandbox', sandbox_token='controlled')
    work, _, _ = await facts(sessions, users['employee'])
    ReceiptClient.runs, ReceiptClient.count = {}, 0
    monkeypatch.setattr('app.modules.executions.service.SandboxClient', ReceiptClient)
    message = await sent(clients['peer'], '生成我自己的文件')
    epochs = []

    class FileModel(ReviewedFixtureModel):
        calls: int = 0
        async def _agenerate(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                answer = AIMessage(content='', tool_calls=[{'id': 'file-once', 'name': 'run_python', 'args': {'code': 'print(3)', 'title': '私人成果'}}])
            else:
                assert self.calls == 2
                async with sessions() as db:
                    epochs.append((await db.get(ConversationContext, message['conversationId'])).invalidation_version)
                response = await clients['employee'].request('DELETE', '/api/v1/work-items/' + work.id, json={'expectedRevision': 1})
                assert response.status_code == 200, response.text
                async with sessions() as db:
                    epochs.append((await db.get(ConversationContext, message['conversationId'])).invalidation_version)
                answer = completion('私人成果已生成。')
            return ChatResult(generations=[ChatGeneration(message=answer)])

    job = await claim(sessions, users['peer'].id)
    fake = FileModel(model='controlled', api_key='controlled')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=fake)
    result = (await clients['peer'].get('/api/v1/messages/' + message['messageId'])).json()
    assert result['job']['state'] == 'succeeded' and result['reply'] == '私人成果已生成。', result
    assert epochs == [0, 0] and fake.calls == 2 and ReceiptClient.count == 1
    assert len(result['deliverables']) == 1
    assert (await clients['peer'].get(result['deliverables'][0]['files'][0]['url'])).content == ReceiptClient.data
    async with sessions() as db:
        assert (await db.get(WorkItem, work.id)).deleted
        saved = await db.get(Job, job.id)
        assert not saved.error and not saved.access.get('team')
