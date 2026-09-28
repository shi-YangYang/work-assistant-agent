import pytest
from datetime import timedelta
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.agent.harness import invoke_harness
from app.modules.conversations.models import ConversationContext
from app.modules.messages.models import Message
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.queue import claim
from fakes import controlled_model
from test_company import send

pytestmark = pytest.mark.asyncio


async def test_real_graph_compacts_durably_and_next_task_reuses_snapshot(setup):
    from app.agent.operations import execute
    from app.tasks.context import InputChanged
    from test_business_actions import create, read_work, Judge
    settings, sessions, users, clients = setup
    actor = users['employee']
    work = await create(clients['employee'], title='原始计划')
    sent = await send(clients['employee'], '继续讨论方案，先不写入工作。')
    async with sessions.begin() as db:
        current = await db.get(Message, sent['messageId'])
        for index in range(24):
            db.add(Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=current.conversation_id,
                           text='历史方案讨论。' * 250, reply='明确阶段目标后再执行。' * 100,
                           created_at=current.created_at - timedelta(minutes=index + 1)))
    job = await claim(sessions, actor.id)
    cap = {'contextWindow': 64000, 'inputLimit': None, 'maxOutput': 4000, 'source': 'override'}
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0,
                         model_binding={'assistant': {'model': 'controlled-test', 'contextCapability': cap}}, intent_model=Judge())
    await read_work(context, work['id'])
    model = controlled_model('clarify')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        answer = await invoke_harness(context, saver, '继续讨论方案，先不写入工作。', model)
        assert answer and model.summaries
        async with sessions() as db:
            store = await db.get(ConversationContext, current.conversation_id)
            assert store.payload['summary'] and len(store.payload['summarySources']) >= 20
            live = await db.get(Job, job.id)
            usage = live.result['contextUsage']
            assert usage['state'] == 'ready' and usage['afterTokens'] < usage['beforeTokens']
            assert usage['afterTokens'] < 64000 * .9
        # A completed graph restore must not repeat model calls or summary work.
        count = len(model.summaries)
        from app.agent.compaction import saved_packet, save_packet
        packet = await saved_packet(context)
        packet['evidence'] = [{'key': 'controlled-call', 'tool': 'find_work_items', 'result': '{"items": []}'}]
        await save_packet(context, packet)
        # The task completed a write after summarizing its v1 read, then lost
        # the process before review. The real receipt authenticates v1 -> v2.
        updated = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'title': '调整后的计划'})
        assert updated['state'] == 'succeeded' and updated['objectRevision'] == 2
        assert packet['dependencies']['business'][work['id']] == 1
        resumed = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0,
                             model_binding=context.model_binding, read_versions={work['id']: 2})
        assert await invoke_harness(resumed, saver, '继续讨论方案，先不写入工作。', model) == answer
        assert any(row['tool'] == 'find_work_items' for row in resumed.reply_evidence)
        assert len(model.summaries) == count
        async with sessions() as db:
            assert (await db.get(ConversationContext, current.conversation_id)).payload['summaryDependencies']['business'][work['id']] == 2
        # An unrelated newer edit has no receipt in this task and must still
        # prevent reuse, even if a fresh worker already knows its revision.
        from app.modules.work.service import save_work
        async with sessions.begin() as db:
            await save_work(db, actor, {'title': '外部修改'}, identifier=work['id'], expected=2)
        external = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0,
                              model_binding=context.model_binding, read_versions={work['id']: 3})
        with pytest.raises(InputChanged):
            await invoke_harness(external, saver, '继续讨论方案，先不写入工作。', model)


async def test_unknown_window_does_not_invent_compaction(setup):
    settings, sessions, users, clients = setup
    sent = await send(clients['employee'], '只回复一句话')
    actor = users['employee']; job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    model = controlled_model('clarify')
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await invoke_harness(context, saver, '只回复一句话', model)
    async with sessions() as db:
        usage = (await db.get(Job, job.id)).result['contextUsage']
        assert usage['contextWindow'] is None and usage['capacitySource'] == 'unknown'
        assert usage['usedTokens'] > 0 and not model.summaries


async def test_summary_can_cross_report_boundary_and_invalidates_with_source(setup):
    from app.agent.report_context import capture_brief, load_brief
    from app.modules.conversations.context_store import references, capture_sources, publish_summary
    from app.modules.conversations.context_invalidation import invalidate
    from app.tasks.context import InputChanged
    from uuid import uuid4
    settings, sessions, users, clients = setup
    actor = users['employee']; first = await send(clients['employee'], '请保持简洁')
    job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    async with sessions.begin() as db:
        current = await db.get(Message, first['messageId'])
        await references(db, actor, job, current)
        sources = await capture_sources(db, actor, current)
    await publish_summary(context, {'id': 'summary', 'summary': '用户要求简洁。', 'covered': [first['messageId']], 'sources': sources})
    async with sessions.begin() as db:
        completed = await db.get(Job, job.id)
        completed.state, completed.lease_until = 'awaiting_input', None
    reply = await clients['employee'].post('/api/v1/messages', json={'text': '按刚才要求生成报告', 'conversationId': first['conversationId']}, headers={'Idempotency-Key': uuid4().hex})
    assert reply.status_code == 202
    async with sessions.begin() as db:
        current = await db.get(Message, reply.json()['messageId'])
        source = await capture_brief(db, actor, current, job)
        report_job = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id='controlled-reference', result={'instructionSource': source})
        loaded = await load_brief(db, actor, report_job)
        assert loaded[0]['id'] == 'context-summary' and '简洁' in loaded[0]['assistantReference']
    async with sessions.begin() as db:
        await invalidate(db, conversation_id=first['conversationId'])
    async with sessions() as db:
        with pytest.raises(ValueError, match='上下文已变化'):
            await load_brief(db, actor, report_job)
