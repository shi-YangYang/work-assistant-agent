"""Hard-stop delivery rechecks recovered prose without rerunning any work."""
import pytest
from sqlalchemy import func, select

from app.agent.actions.operations import execute
from app.agent.completion.budget import deliver
from app.modules.memories import service as memories
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks.feedback.reply_stream import dto, source_snapshot
from app.tasks.lease import lease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from test_business_actions import create, runtime
from test_sandbox_execution import receipts, run as run_code

pytestmark = pytest.mark.asyncio


async def prepare(setup, text='请整理当前资料'):
    context, sent = await runtime(setup, text)
    context.node_retry = True
    await initialize(context, 'hard-stop')
    return context, sent


async def prefix(context, monkeypatch, storage, text, *, source=None):
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        source = source if source is not None else source_snapshot(context, job)
        persisted = storage != 'redis'
        job.feedback = {**job.feedback, 'replyStreamCall': 'call', 'replyStreamSource': source,
            'replyStream': {'version': 1 if persisted else 2, 'generation': 1,
                            'state': 'interrupted' if persisted else 'streaming',
                            'text': text if persisted else ''}}
    async def snapshot(*args):
        if storage == 'persisted':
            return None
        return {'attempt': context.attempt, 'fence': context.fence - int(storage == 'stale_redis'),
                'callId': 'call', 'generation': 1, 'source': source, 'sealed': False,
                'text': '旧 worker 的迟到正文' if storage == 'stale_redis' else text}
    monkeypatch.setattr('app.tasks.feedback.reply_stream.temporary_snapshot', snapshot)


async def delivered(setup, context, sent):
    async with context.sessions() as db:
        before = (await db.get(Job, context.job_id)).result['taskBudget']['models']
    await deliver(context, 'time')
    response = await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['reply'] and not result['job']['error']
    assert all(name not in response.text for name in ('taskBudget', 'deadlineAt', 'reserve_models', '工具额度'))
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['taskBudget']['endedAt'] is not None
        assert job.result['taskBudget']['models'] == before
    return result


@pytest.mark.parametrize('storage', ['redis', 'persisted', 'stale_redis'])
@pytest.mark.parametrize('change', ['unchanged', 'revision', 'deleted', 'owner'])
async def test_hard_stop_rechecks_all_prefix_sources(setup, monkeypatch, storage, change):
    context, sent = await prepare(setup)
    work = await create(setup[3]['employee'], title='待变更来源')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        source = {**source_snapshot(context, job), 'reads': {work['id']: 1}}
        item = await db.get(WorkItem, work['id'])
        if change == 'revision':
            item.revision += 1
        elif change == 'deleted':
            item.deleted = True
        elif change == 'owner':
            item.owner_id = setup[2]['peer'].id
    marker = '已经输出的资料分析片段'
    await prefix(context, monkeypatch, storage, marker, source=source)
    if storage != 'redis' and change != 'unchanged':
        async with context.sessions() as db:
            job, actor = await lease(db, context)
            assert (await dto(db, actor, job, await db.get(Message, sent['messageId'])))['state'] == 'withdrawn'
    result = await delivered(setup, context, sent)
    assert (marker in result['reply']) is (change == 'unchanged')
    assert '旧 worker 的迟到正文' not in result['reply']
    assert result['job']['taskOutcome']['state'] == ('partial' if change == 'unchanged' else 'blocked')
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert (marker in job.result['conversationReply']) is (change == 'unchanged')
        if change != 'unchanged':
            assert job.feedback['replyStream']['state'] == 'withdrawn'
            assert job.feedback['replyStream']['text'] == ''


@pytest.mark.parametrize('storage', ['redis', 'persisted'])
@pytest.mark.parametrize('change', ['unchanged', 'edited', 'cleared', 'disabled'])
async def test_hard_stop_respects_current_memory_barrier(setup, monkeypatch, storage, change):
    context, sent = await prepare(setup, '我喜欢吃米饭，请记住')
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        memory = await memories.bind(db, actor, job, 0)
        saved = await memories.change(db, actor, job, memory, call_id='save-rice',
            evidence='我喜欢吃米饭', new='喜欢吃米饭', explicit=True)
        assert saved['state'] == 'succeeded'
        if change in ('edited', 'cleared'):
            await memories.save_document(db, actor, 1, '喜欢面食' if change == 'edited' else '')
        elif change == 'disabled':
            await memories.settings(db, actor, 1, False)
        expected = memories.dto(await memories.read(db, actor))
    if change != 'unchanged':
        async with context.sessions() as db:
            job, actor = await lease(db, context)
            with pytest.raises(ValueError, match='记忆已被修改或删除'):
                await memories.validate_job(db, actor, job)
    marker = '我已记住你喜欢吃米饭。'
    await prefix(context, monkeypatch, storage, marker)
    result = await delivered(setup, context, sent)
    assert (marker in result['reply']) is (change == 'unchanged')
    assert result['job']['taskOutcome']['state'] == ('partial' if change == 'unchanged' else 'blocked')
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert (marker in job.result['conversationReply']) is (change == 'unchanged')
        assert memories.dto(await memories.read(db, setup[2]['employee'])) == expected


@pytest.mark.parametrize('storage', ['redis', 'persisted'])
async def test_invalid_prose_keeps_valid_files_and_committed_receipts(setup, monkeypatch, receipts, storage):
    context, sent = await prepare(setup, '创建一项报价方案工作，生成文件，然后整理资料')
    action = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    assert action['state'] == 'succeeded', action
    generated = await run_code(context)
    assert generated['state'] == 'succeeded', generated
    before_calls = receipts.count
    work = await create(setup[3]['employee'], title='另一个已变更来源')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        source = {**source_snapshot(context, job), 'reads': {work['id']: 1}}
        (await db.get(WorkItem, work['id'])).revision += 1
    await prefix(context, monkeypatch, storage, '不得交付的过期正文', source=source)
    result = await delivered(setup, context, sent)
    assert '不得交付的过期正文' not in result['reply']
    assert '创建工作《报价方案》：已完成' in result['reply']
    assert '已整理《计算结果》' in result['reply']
    assert result['job']['taskOutcome']['state'] == 'partial'
    assert [(row['id'], row['state']) for row in result['actions']] == [(action['id'], 'succeeded')]
    assert result['deliverables'][0]['files'] == generated['delivery']['files']
    file = await setup[3]['employee'].get(result['deliverables'][0]['files'][0]['url'])
    assert file.status_code == 200 and file.content == receipts.data
    assert receipts.count == before_calls == 1
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == sent['messageId'])) == 1
        assert (await db.get(WorkItem, action['objectId'])).revision == 1
