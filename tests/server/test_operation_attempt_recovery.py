"""A later authorized user turn can replace only an unwritten failed attempt."""
import pytest
from sqlalchemy import select

from app.agent.actions.operations import execute
from app.core.errors import problem
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem, WorkRevision
from test_business_actions import create, read_work, runtime
from test_conversation_task_state import ScopedJudge, close_task

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('status, state', [(409, 'conflict'), (422, 'failed')])
async def test_new_authorized_message_recovers_failed_atomic_item_once(setup, monkeypatch, status, state):
    from app.agent.actions import operations
    _, sessions, users, clients = setup
    work = await create(clients['employee'], '培训协调', summary='待更正', dueDate='2026-09-30')
    original_perform = operations.perform

    async def fail_after_write(db, actor, row, job=None, **kwargs):
        await original_perform(db, actor, row, job, **kwargs)
        problem(status, '受控故障，事务已回滚')

    monkeypatch.setattr(operations, 'perform', fail_after_write)
    first, sent = await runtime(setup, '更正培训协调的说明，保留截止日期')
    await read_work(first, work['id'])
    arguments = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'summary': '正确说明'})
    failed = await execute(first, **arguments)
    assert failed['state'] == state
    assert (await execute(first, **arguments))['id'] == failed['id']
    changed = await execute(first, **{**arguments, 'changes': {'summary': '换措辞继续猜'}})
    assert changed['state'] == 'conflict'
    async with sessions() as db:
        actual = await db.get(WorkItem, work['id'])
        assert actual.revision == 1 and actual.content['summary'] == '待更正'
        assert len((await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == users['employee'].id))).all()) == 1
    await close_task(first, state='blocked')
    monkeypatch.setattr(operations, 'perform', original_perform)

    current, next_sent = await runtime(setup, '现在请重新更正并保存，其他字段不变')
    current.intent_model = ScopedJudge(resume=True)
    arguments['task_item_id'] = failed['taskItemId']
    # A new message alone does not bypass the fresh-read gate.
    missing_read = await execute(current, **arguments)
    assert missing_read['state'] == 'conflict' and '读取目标的最新版本' in missing_read['message']
    await read_work(current, work['id'])
    recovered = await execute(current, **arguments)
    assert recovered['state'] == 'succeeded' and recovered['id'] != failed['id']
    assert recovered['taskItemId'] == failed['taskItemId']
    assert recovered['messageId'] == next_sent['messageId']
    assert (await execute(current, **arguments))['id'] == recovered['id']
    assert current.intent_model.inputs[-1]['currentUserText'] == '现在请重新更正并保存，其他字段不变'
    async with sessions() as db:
        records = (await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == users['employee'].id))).all()
        assert len(records) == 2
        old = await db.get(BusinessAction, failed['id'])
        assert old.state == state and old.message_id == sent['messageId']
        assert old.result['message'] == '受控故障，事务已回滚'
        assert old.task_item_key is None and old.result['originalTaskItemId'] == failed['taskItemId']
        saved = await db.get(WorkItem, work['id'])
        assert saved.revision == 2 and saved.content['summary'] == '正确说明'
        assert saved.content['dueDate'] == '2026-09-30'
        assert len((await db.scalars(select(WorkRevision).where(WorkRevision.work_id == work['id']))).all()) == 2
    old_message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(old_message['actions']) == 1
    assert old_message['actions'][0]['id'] == failed['id'] and old_message['actions'][0]['state'] == state
    assert old_message['actions'][0]['taskItemId'] == failed['taskItemId']
    await close_task(current, state='needs_input', relation='continue')
    third, _ = await runtime(setup, '刚才那条处理得怎么样，继续同一项即可')
    third.intent_model = ScopedJudge(resume=True)
    await read_work(third, work['id'])
    replay = await execute(third, **{**arguments, 'expected_revision': 2})
    assert replay['id'] == recovered['id']
    async with sessions() as db:
        assert (await db.get(WorkItem, work['id'])).revision == 2


@pytest.mark.parametrize('state', ['pending', 'cancelled', 'succeeded'])
async def test_continuation_does_not_replace_nonfailed_receipts(setup, state):
    _, sessions, users, clients = setup
    first, _ = await runtime(setup, '准备创建协调工作，然后还有第二件事')
    first.intent_model = ScopedJudge(preview=state != 'succeeded')
    arguments = dict(step=1, action='create_work', changes={'title': '只创建一项'})
    saved = await execute(first, **arguments)
    await close_task(first, state='needs_input')
    if state == 'cancelled':
        cancelled = await clients['employee'].post('/api/v1/business-actions/' + saved['id'] + '/cancel', json={'expectedRevision': saved['revision']})
        assert cancelled.status_code == 200
        # The HTTP cancellation schedules an ordinary acknowledgement turn.
        # Complete that turn before sending the next user message.
        from app.tasks.context import RunContext
        from app.tasks.runtime.queue import claim
        acknowledgement = await claim(sessions, users['employee'].id)
        assert acknowledgement.id == cancelled.json()['continuation']['jobId']
        context = RunContext(acknowledgement.owner_id, acknowledgement.company_id, acknowledgement.id,
                             acknowledgement.fence, sessions, first.settings, source_revision=0)
        await close_task(context, state='needs_input', relation='continue')
    context, _ = await runtime(setup, '继续刚才的任务，先看看第一件事')
    context.intent_model = ScopedJudge(resume=True)
    resumed = await execute(context, **arguments, task_item_id=saved['taskItemId'])
    assert resumed['id'] == saved['id'] and resumed['state'] == state
    async with sessions() as db:
        rows = (await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == users['employee'].id))).all()
        assert len(rows) == 1 and rows[0].task_item_key == saved['taskItemId']
        works = (await db.scalars(select(WorkItem).where(WorkItem.owner_id == users['employee'].id))).all()
        assert len(works) == (1 if state == 'succeeded' else 0)
