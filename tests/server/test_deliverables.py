import json
from types import SimpleNamespace
import pytest
from sqlalchemy import func, select
from app.agent.operations import execute
from app.agent.tools.deliverables import read_deliverable, save_deliverable
from app.agent.deliverable_context import deliverable_context
from app.modules.deliverables.models import Deliverable, DeliverableRevision, DeliverableLink
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkRevision
from app.tasks.models import Job
from test_business_actions import runtime, finish, read_work
from test_company import keyed

pytestmark = pytest.mark.asyncio


async def save_plan(context, **params):
    return json.loads(await save_deliverable.coroutine(runtime=SimpleNamespace(context=context), **params))


async def read_plan(context, identifier='', revision=0):
    return json.loads(await read_deliverable.coroutine(runtime=SimpleNamespace(context=context), deliverable_id=identifier, revision=revision))


async def test_same_message_exposes_final_version_and_recovers_saved_edit_response(setup):
    _, sessions, users, clients = setup
    context, sent = await runtime(setup, '给一个完整的三步方案')
    first = await save_plan(context, title='实施方案', body='初稿', items=[{'title': '澄清需求'}])
    params = dict(title='实施方案', body='完整计划', items=[*first['items'], {'title': '接口联调'}, {'title': '试运行'}], deliverable_id=first['id'], expected_revision=1, step=2)
    second = await save_plan(context, **params)
    assert second['revision'] == 2
    # The write committed, but its tool response was lost before journaling.
    # A new execution context restores a v2 read, while replaying v1 arguments.
    context.deliverable_reads.clear()
    replay = await save_plan(context, **params)
    assert replay['state'] == 'succeeded' and replay['revision'] == 2
    changed = await save_plan(context, **{**params, 'body': '修改了重试输入'})
    assert changed['state'] == 'conflict'
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert [(item['id'], item['revision']) for item in message['deliverables']] == [(first['id'], 2)]
    old = (await clients['employee'].get(f"/api/v1/deliverables/{first['id']}?revision=1")).json()
    assert old['body'] == '初稿'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision).where(DeliverableRevision.owner_id == users['employee'].id)) == 2


async def test_private_versions_stable_items_links_and_dates(setup):
    _, sessions, users, clients = setup
    context, sent = await runtime(setup, '整理客户实施计划，不记录工作')
    original = dict(title='客户实施计划', body='范围与待确认问题', items=[{'title': '需求核对', 'body': '列出缺失信息'}, {'title': '接口开发', 'body': '按文档实现'}])
    first = await save_plan(context, **original)
    assert first['state'] == 'succeeded' and first['revision'] == 1
    again = await save_plan(context, **original)
    assert again['id'] == first['id'] and again['revision'] == 1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 0
    await finish(context)
    context, _ = await runtime(setup, '交换顺序，接口开发改名为接口联调，只改方案')
    read = await read_plan(context, first['id'])
    updated = [{**read['items'][1], 'title': '接口联调'}, read['items'][0]]
    second = await save_plan(context, deliverable_id=first['id'], expected_revision=1, title=first['title'], body=first['body'], items=updated)
    assert second['revision'] == 2 and second['items'][0]['id'] == first['items'][1]['id']
    old = (await clients['employee'].get(f"/api/v1/deliverables/{first['id']}?revision=1")).json()
    assert old['items'] == first['items'] and old['latestRevision'] == 2
    await finish(context)
    context, _ = await runtime(setup, '把现在方案的第一项加入我的工作')
    await read_plan(context, first['id'])
    created = await execute(context, step=1, action='create_work', changes={'title': '接口联调', 'summary': '按文档实现'}, deliverable_id=first['id'], deliverable_revision=2, item_id=second['items'][0]['id'])
    assert created['state'] == 'succeeded', created
    replay = await execute(context, step=1, action='create_work', changes={'title': '接口联调', 'summary': '按文档实现'}, deliverable_id=first['id'], deliverable_revision=2, item_id=second['items'][0]['id'])
    assert replay['objectId'] == created['objectId']
    selection = context.intent_model.inputs[-1]['proposedOperation']['deliverableSelection']
    assert selection['items'][0]['id'] == first['items'][1]['id']
    await finish(context)
    context, _ = await runtime(setup, '第一项截止日改到2026-10-09，其他不变')
    linked = await read_plan(context, first['id'])
    assert linked['links'][0]['workId'] == created['objectId']
    work = await read_work(context, created['objectId'])
    changed = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=work['revision'], changes={'dueDate': '2026-10-09'}, deliverable_id=first['id'], deliverable_revision=2, item_id=second['items'][0]['id'])
    assert changed['state'] == 'succeeded'
    saved = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['summary'] == '按文档实现' and saved['dueDate'] == '2026-10-09'
    assert (await read_plan(context, first['id']))['revision'] == 2
    assert (await clients['admin'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404
    for who in ('admin', 'peer', 'outsider'):
        assert (await clients[who].get('/api/v1/deliverables/' + first['id'])).status_code == 404
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableLink).where(DeliverableLink.owner_id == users['employee'].id)) == 2
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']).order_by(WorkRevision.revision.desc()))
        assert revision.source_ids == [] and revision.publication['content']['dueDate'] == '2026-10-09'


async def test_conflict_foreign_items_and_cross_conversation_reference(setup):
    _, sessions, users, clients = setup
    context, sent = await runtime(setup, '写一个清单')
    first = await save_plan(context, title='清单', body='', items=[{'title': '同名任务'}, {'title': '同名任务'}])
    assert first['items'][0]['id'] != first['items'][1]['id']
    changed_retry = await save_plan(context, title='被改写的重试', body='新正文')
    assert changed_retry['state'] == 'conflict'
    await finish(context)
    context, _ = await runtime(setup, '改清单')
    bad = await save_plan(context, deliverable_id=first['id'], expected_revision=1, title='清单', body='新正文')
    assert bad['state'] == 'conflict'
    await read_plan(context, first['id'])
    bad_item = await save_plan(context, deliverable_id=first['id'], expected_revision=1, title='清单', body='', items=[{'id': 'invented', 'title': '伪造'}])
    assert bad_item['state'] == 'conflict'
    next_version = await save_plan(context, deliverable_id=first['id'], expected_revision=1, title='清单', body='', items=list(reversed(first['items'])))
    assert next_version['revision'] == 2
    # Another worker's old read cannot overwrite the now-current version.
    await finish(context)
    context, _ = await runtime(setup, '继续修改')
    await read_plan(context, first['id'], 1)
    stale = await save_plan(context, deliverable_id=first['id'], expected_revision=1, title='过期', body='覆盖')
    assert stale['state'] == 'conflict'
    other = (await clients['employee'].post('/api/v1/conversations', json={'title': '另一会话'})).json()
    response = await clients['employee'].post('/api/v1/messages', headers=keyed(), json={'conversationId': other['id'], 'text': '继续改', 'deliverableReference': {'id': first['id'], 'revision': 1, 'itemIds': []}})
    assert response.status_code == 404
    response = await clients['peer'].post('/api/v1/messages', headers=keyed(), json={'text': '继续改', 'deliverableReference': {'id': first['id'], 'revision': 1, 'itemIds': []}})
    assert response.status_code == 404


async def test_old_plan_survives_history_window_and_message_reference_is_idempotent(setup):
    _, sessions, users, clients = setup
    context, sent = await runtime(setup, '写一个长期方案')
    first = await save_plan(context, title='长期方案', body='完整正文', items=[{'title': '第一项'}])
    await finish(context)
    for index in range(14):
        context, _ = await runtime(setup, f'日常交流{index}')
        await finish(context)
    context, _ = await runtime(setup, '继续之前的长期方案')
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        current = await db.get(Message, job.target_id)
        catalog = await deliverable_context(db, users['employee'], current)
        assert catalog['items'][0]['id'] == first['id']
    ref = {'id': first['id'], 'revision': 1, 'itemIds': [first['items'][0]['id']]}
    body = {'conversationId': sent['conversationId'], 'text': '只改这一项', 'deliverableReference': ref}
    headers = keyed()
    once = await clients['employee'].post('/api/v1/messages', headers=headers, json=body)
    twice = await clients['employee'].post('/api/v1/messages', headers=headers, json=body)
    assert once.status_code == 202 and once.json() == twice.json()
    async with sessions() as db:
        assert (await db.get(Message, once.json()['messageId'])).deliverable_reference == ref
    conversation = (await clients['employee'].get('/api/v1/conversations/' + sent['conversationId'])).json()
    deleted = await clients['employee'].request('DELETE', '/api/v1/conversations/' + sent['conversationId'], json={'expectedRevision': conversation['revision']})
    assert deleted.status_code == 200
    assert (await clients['employee'].get('/api/v1/deliverables/' + first['id'])).status_code == 404


async def test_private_revision_delivery_and_existing_link_do_not_claim_business_failure(setup):
    from app.modules.deliverables.serializers import delivery_summary
    from app.modules.operations.receipts import receipt_reply
    from app.agent.reply_review import ReviewedReply
    _, sessions, users, _ = setup
    context, sent = await runtime(setup, '制定计划')
    first = await save_plan(context, title='实施计划', body='范围', items=[{'title': '联调', 'body': '原安排'}])
    async with sessions() as db:
        message = await db.get(Message, sent['messageId'])
        text = await delivery_summary(db, users['employee'], message)
        assert receipt_reply(ReviewedReply(execution_claims=True, verified=True), [], deliverables=text) == '已整理《实施计划》，包含 1 个条目。'
        assert receipt_reply(ReviewedReply(text='这里是完整计划。', execution_claims=True, verified=True), [], deliverables=text) == '这里是完整计划。'
    await finish(context)
    context, sent = await runtime(setup, '把联调改成分两天完成')
    await read_plan(context, first['id'])
    second = await save_plan(context, deliverable_id=first['id'], expected_revision=1, title=first['title'], body='范围', items=[{**first['items'][0], 'body': '分两天完成'}])
    async with sessions() as db:
        text = await delivery_summary(db, users['employee'], await db.get(Message, sent['messageId']))
        assert '第 2 版' in text and '调整了「联调」' in text
    await finish(context)
    context, _ = await runtime(setup, '把第一项加入我的工作')
    await read_plan(context, first['id'])
    params = dict(step=1, action='create_work', changes={'title': '联调'}, deliverable_id=first['id'], deliverable_revision=2, item_id=second['items'][0]['id'])
    assert (await execute(context, **params))['state'] == 'succeeded'
    await finish(context)
    context, _ = await runtime(setup, '再把第一项加入我的工作')
    await read_plan(context, first['id'])
    assert (await execute(context, **params))['state'] == 'conflict'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 1


async def test_tool_result_paging_keeps_stable_items_and_declares_incomplete_text():
    from app.agent.tools.deliverables import model_page
    result = {'body': '正文' * 5000, 'items': [{'id': 'stable', 'title': '条目', 'body': '材料' * 4000}]}
    first = model_page(result)
    second = model_page(result, first['nextOffset'])
    assert first['contentTruncated'] and first['nextOffset'] == second['contentOffset']
    assert first['items'][0]['id'] == second['items'][0]['id'] == 'stable'
    assert len(first['body']) + len(first['items'][0]['body']) <= 10000
    assert result['body'] == '正文' * 5000
