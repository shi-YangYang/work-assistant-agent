"""Same-task recovery must use checked identities, not rewritten arguments."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import update

from app.agent.actions.operations import execute
from app.agent.actions.task_items import bind, recovery_candidates, reference_error
from app.core.digests import digest
from app.agent.tools.business.work import propose_progress
from app.tasks.feedback.outcomes import derive
from app.tasks.models import Job
from app.modules.work.models import WorkRevision, WorkUpdate
from _support.agent.business_actions import Judge, create, read_work, runtime
from _support.agent.conversation_task_state import ScopedJudge, close_task
from _support.materials.deliverables import read_plan, save_plan
from _support.agent.execution_permissions import mode_runtime
from _support.work.work_records import body


class RecoveryJudge(Judge):
    def __init__(self, item_id):
        super().__init__()
        self.item_id = item_id

    async def ainvoke(self, messages):
        response = await super().ainvoke(messages)
        return AIMessage(content=json.dumps({**json.loads(response.content), 'taskItemId': self.item_id}))


@pytest.mark.asyncio
@pytest.mark.parametrize('window', ['authorization', 'bound'])
@pytest.mark.parametrize('independent', [True, False])
async def test_concurrent_malformed_attempt_invalidates_authorization(setup, monkeypatch, window, independent):
    from app.agent.actions import operations
    from app.modules.operations.models import BusinessAction
    from sqlalchemy import select

    context, _ = await mode_runtime(setup, 'full', '创建两项同名工作，一项整理资料，一项安排会议，分别保存完整正文'
                                   if independent else '创建一项同名工作，正文写整理资料')
    first_changes = {'title': '同名工作', 'body': {'schemaVersion': 1, 'content': '整理资料'}}
    first = await execute(context, step=1, action='create_work', changes=first_changes)
    entered, resume = asyncio.Event(), asyncio.Event()

    class PausedJudge(RecoveryJudge):
        async def ainvoke(self, messages):
            result = await super().ainvoke(messages)
            if window == 'authorization':
                entered.set()
                await resume.wait()
            return result

    judge = PausedJudge(first['taskItemId'])
    context.intent_model = judge
    original_authorize = operations.authorize_intent

    async def pause_after_binding(*args, **kwargs):
        result = await original_authorize(*args, **kwargs)
        if window == 'bound':
            entered.set()
            await resume.wait()
        return result

    monkeypatch.setattr(operations, 'authorize_intent', pause_after_binding)
    valid = dict(step=1, action='create_work', task_item_id=first['taskItemId'],
                 changes={'title': '同名工作', 'body': body('整理资料')})
    writing = asyncio.create_task(execute(context, **valid))
    await asyncio.wait_for(entered.wait(), 5)
    second_changes = {'title': '同名工作', 'body': {'schemaVersion': 1, 'content': [
        {'type': 'paragraph', 'content': '安排会议' if independent else '整理资料'}]}}
    try:
        second = await execute(context, step=2, action='create_work', task_item_id=first['taskItemId'], changes=second_changes)
    finally:
        resume.set()
    saved = await writing
    assert second['state'] == 'failed' and second['taskItemId'] == first['taskItemId']
    assert saved['state'] in ('failed', 'conflict') and saved['category'] == 'conflict'
    assert '事项尝试已变化' in saved['diagnostic'] and len(judge.inputs) == 1
    assert 'invalidAttempts' not in judge.inputs[0]['recoveringItem']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        job.state = 'succeeded'
        assert not await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id))
        assert all(not item.get('receiptId') for item in job.result['taskItems'])
        assert [attempt['changes'] for attempt in job.result['taskItems'][0]['invalidAttempts']] == [first_changes, second_changes]
        failures = [item for item in job.result['toolOutcomes'] if item['category'] == 'invalid_arguments']
        assert len(failures) == 2
        assert {item['diagnostic'] for item in failures} == {first['diagnostic'], second['diagnostic']}
        assert derive(job, [])['state'] == 'blocked'
        print(json.dumps({'window': window, 'independent': independent, 'authorizationSaw': judge.inputs[0]['recoveringItem'],
                          'taskItems': job.result['taskItems'], 'toolOutcomes': job.result['toolOutcomes'],
                          'rejected': saved}, ensure_ascii=False))
    assert not (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    if not independent:
        # Fresh ordinary authorization sees the whole chain; the stale result
        # must not install a permanent refusal or poison this invocation.
        context.intent_model = RecoveryJudge(first['taskItemId'])
        recovered = await execute(context, **valid)
        assert recovered['state'] == 'succeeded'
        assert context.intent_model.inputs[0]['recoveringItem']['invalidAttempts'][-1]['changes'] == second_changes
        async with context.sessions() as db:
            job = await db.get(Job, context.job_id)
            job.state = 'succeeded'
            assert derive(job, [recovered])['state'] == 'completed'


@pytest.mark.asyncio
async def test_missing_information_same_item_and_slot_require_new_evidence(setup):
    context, _ = await mode_runtime(setup, 'full', '为两条方案分别建立工作，缺失内容先问我')
    judge = Judge(False, failure_kind='missing_info')
    context.intent_model = judge
    first = await execute(context, step=1, action='create_work', changes={'title': '甲'})
    renamed = await execute(context, step=1, action='create_work', changes={'title': '甲整理版'}, task_item_id=first['taskItemId'])
    omitted = await execute(context, step=1, action='create_work', changes={'title': '甲另一个说法'})
    assert renamed['taskItemId'] == omitted['taskItemId'] == first['taskItemId']
    assert len(judge.inputs) == 1
    second = await execute(context, step=2, action='create_work', changes={'title': '乙'})
    assert second['taskItemId'] != first['taskItemId'] and len(judge.inputs) == 2
    context.intent_model = RecoveryJudge(first['taskItemId'])
    guessed = await execute(context, step=3, action='create_work', changes={'title': '甲再次整理版'})
    assert guessed['state'] == 'waiting' and guessed['taskItemId'] == first['taskItemId']
    plan = await save_plan(context, title='实施计划', body='', items=[{'title': '甲', 'body': '新取得的准确方案'}])
    await read_plan(context, plan['id'])
    context.intent_model = RecoveryJudge(first['taskItemId'])
    recovered = await execute(context, step=1, action='create_work', changes={'title': '甲', 'body': body('新取得的准确方案')},
        deliverable_id=plan['id'], deliverable_revision=1, item_id=plan['items'][0]['id'], task_item_id=first['taskItemId'])
    assert recovered['state'] == 'succeeded' and len(context.intent_model.inputs) == 1
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        assert [row['taskItemId'] for row in task.result['toolOutcomes'] if row['category'] == 'missing_info'] == [second['taskItemId']]


@pytest.mark.asyncio
async def test_judge_recovers_missing_tool_item_id_without_repeating_another_create(setup):
    context, _ = await mode_runtime(setup, 'full', '把前两项完整方案加入工作')
    context.intent_model = Judge(False)
    failed = await execute(context, step=1, action='create_work', changes={'title': '联调方案', 'body': body('对照接口完成联调')})
    other = await execute(context, step=2, action='create_work', changes={'title': '需求方案', 'body': body('确认需求与范围')})
    plan = await save_plan(context, title='实施计划', body='', items=[
        {'title': '接口联调', 'body': '对照接口完成联调'}, {'title': '需求确认', 'body': '确认需求与范围'}])
    await read_plan(context, plan['id'])
    context.intent_model = RecoveryJudge(failed['taskItemId'])
    first = await execute(context, step=1, action='create_work', changes={'title': '接口联调', 'body': body('对照接口完成联调，记录验收结果')},
        deliverable_id=plan['id'], deliverable_revision=1, item_id=plan['items'][0]['id'])
    assert first['state'] == 'succeeded' and first['taskItemId'] == failed['taskItemId']
    payload = context.intent_model.inputs[0]
    candidates = payload['failedItemCandidates']
    assert len(context.intent_model.inputs) == 1 and len(candidates) == 2
    original = next(item for item in candidates if item['id'] == failed['taskItemId'])
    assert original['attemptedOperation']['changes']['title'] == '联调方案'
    assert original['userSource']['userText'] == '把前两项完整方案加入工作'
    assert original['failure']['category'] == 'invalid_arguments'
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        assert [row['taskItemId'] for row in task.result['toolOutcomes'] if row['category'] == 'invalid_arguments'] == [other['taskItemId']]
    context.intent_model = RecoveryJudge(other['taskItemId'])
    second = await execute(context, step=2, action='create_work', changes={'title': '需求确认', 'body': body('确认需求与范围')},
        deliverable_id=plan['id'], deliverable_revision=1, item_id=plan['items'][1]['id'])
    assert second['state'] == 'succeeded' and second['taskItemId'] == other['taskItemId']
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert not task.result['operationFeedback'] and derive(task, [first, second])['state'] == 'completed'
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert {work['id'] for work in works} == {first['objectId'], second['objectId']}


@pytest.mark.asyncio
async def test_compat_suggestion_actual_correction_clears_only_its_bound_failure(setup):
    context, _ = await mode_runtime(setup, 'full', '记录甲乙两项进展')
    runtime = SimpleNamespace(context=context)
    context.intent_model = Judge(False)
    first = json.loads(await propose_progress.coroutine('甲', '错误摘要', 'in_progress', '', '', runtime))
    other = json.loads(await propose_progress.coroutine('乙', '未完成摘要', 'in_progress', '', '', runtime))
    assert first['taskItemId'] and other['taskItemId'] != first['taskItemId']
    context.intent_model = RecoveryJudge(first['taskItemId'])
    corrected = json.loads(await propose_progress.coroutine('甲', '修正后的完整摘要', 'in_progress', '', '', runtime))
    assert corrected['state'] == 'succeeded' and corrected['taskItemId'] == first['taskItemId']
    assert len(context.intent_model.inputs) == 1
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        failures = [row for row in task.result['toolOutcomes'] if row['category'] == 'invalid_arguments']
        assert [row['taskItemId'] for row in failures] == [other['taskItemId']]
        saved = next(item for item in task.result['taskItems'] if item['id'] == first['taskItemId'])
        assert saved['state'] == 'succeeded' and saved['receiptId'] == corrected['draftId']
    context.intent_model = RecoveryJudge(other['taskItemId'])
    second = json.loads(await propose_progress.coroutine('乙', '完整摘要', 'in_progress', '', '', runtime))
    assert second['state'] == 'succeeded'
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert derive(task)['state'] == 'completed'
    assert len((await setup[3]['employee'].get('/api/v1/work-items')).json()['items']) == 2


@pytest.mark.parametrize('changed', [
    {'targetId': 'other'}, {'sourceTokens': ['other-source']}, {'changes': {'nextStep': '下一步'}},
])
def test_suggestion_item_cannot_be_reassigned_to_other_source_target_or_fields(changed):
    original = {'action': 'propose_progress', 'targetId': 'work', 'sourceTokens': ['source'], 'changes': {'summary': '进展'}}
    item = {'id': 'item', 'action': original['action'], 'targetId': 'work', 'attemptedOperation': original}
    assert reference_error([item], 'item', {**original, **changed})


@pytest.mark.parametrize(('original_copy', 'next_copy'), [(None, 2), (1, 2), (2, None)])
def test_recovery_candidate_preserves_default_copy_identity(original_copy, next_copy):
    original = {'action': 'create_work', 'targetId': '', 'changes': {'title': '同份计划'}}
    proposal = dict(original)
    if original_copy is not None:
        original['copyIndex'] = original_copy
    if next_copy is not None:
        proposal['copyIndex'] = next_copy
    item = {'id': 'copy-item', 'action': 'create_work', 'attemptedOperation': original}
    job = SimpleNamespace(result={'taskItems': [item], 'toolOutcomes': [
        {'taskItemId': item['id'], 'category': 'invalid_arguments', 'message': '补齐创建参数'},
    ]})
    assert reference_error([item], item['id'], proposal)
    assert recovery_candidates(job, proposal) == []


@pytest.mark.asyncio
async def test_distinct_copy_does_not_clear_failed_first_copy_and_first_can_recover(setup):
    context, _ = await mode_runtime(setup, 'full', '把计划建成两份独立工作，内容相同')
    context.intent_model = Judge(False)
    failed = await execute(context, step=1, action='create_work', changes={'title': '同份计划'})
    assert failed['state'] == 'failed' and failed['taskItemId']

    context.intent_model = Judge()
    reused = await execute(context, step=2, action='create_work', changes={'title': '同份计划'},
                           copy_index=2, task_item_id=failed['taskItemId'])
    assert reused['state'] == 'failed' and '副本' in reused['message']
    assert not (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']

    context.intent_model = Judge()
    second = await execute(context, step=2, action='create_work', changes={'title': '同份计划'}, copy_index=2)
    assert second['state'] == 'succeeded' and second['taskItemId'] != failed['taskItemId']
    assert 'failedItemCandidates' not in context.intent_model.inputs[0]
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        assert any(row['taskItemId'] == failed['taskItemId'] and row['category'] == 'invalid_arguments'
                   for row in task.result['toolOutcomes'])
        task.state = 'succeeded'
        assert derive(task, [second])['state'] == 'partial'

    plan = await save_plan(context, title='实施计划', body='', items=[{'title': '同份计划', 'body': '完整实施内容'}])
    await read_plan(context, plan['id'])
    context.intent_model = RecoveryJudge(failed['taskItemId'])
    first = await execute(context, step=1, action='create_work', changes={'title': '同份计划', 'body': body('完整实施内容')},
                          deliverable_id=plan['id'], deliverable_revision=1, item_id=plan['items'][0]['id'])
    assert first['state'] == 'succeeded' and first['taskItemId'] == failed['taskItemId']
    assert [item['id'] for item in context.intent_model.inputs[0]['failedItemCandidates']] == [failed['taskItemId']]
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert derive(task, [first, second])['state'] == 'completed'
        assert not task.result['operationFeedback']
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert {work['id'] for work in works} == {first['objectId'], second['objectId']}


@pytest.mark.asyncio
@pytest.mark.parametrize('relation', ['different_copy', 'different_source', 'same_source_copy'])
async def test_continuation_binds_actual_source_and_copy_before_reusing_receipt(setup, relation):
    context, sent = await runtime(setup, '按计划创建工作，未完成的下一轮继续')
    plan = None
    first_arguments = {'copy_index': 1}
    next_arguments = {'copy_index': 2}
    if relation != 'different_copy':
        plan = await save_plan(context, title='实施计划', body='', items=[
            {'title': '同名事项', 'body': '同样内容'}, {'title': '同名事项', 'body': '同样内容'}])
        await read_plan(context, plan['id'])
        first_arguments = {'deliverable_id': plan['id'], 'deliverable_revision': 1,
                           'item_id': plan['items'][0]['id'], 'copy_index': 2}
        next_arguments = {**first_arguments, 'item_id': plan['items'][1 if relation == 'different_source' else 0]['id']}
    changes = {'title': '同名事项', 'body': body('同样内容')}
    first = await execute(context, step=1, action='create_work', changes=changes, **first_arguments)
    assert first['state'] == 'succeeded'
    await close_task(context, state='needs_input')

    context, _ = await runtime(setup, '继续刚才的计划，处理对应来源和副本，不要重复已有工作')
    context.intent_model = ScopedJudge(resume=True)
    if plan:
        await read_plan(context, plan['id'])
    second = await execute(context, step=1, action='create_work', changes=changes, **next_arguments)
    assert second['state'] == 'succeeded', second
    assert (second['id'] == first['id']) is (relation == 'same_source_copy')
    assert (second['taskItemId'] == first['taskItemId']) is (relation == 'same_source_copy')
    async with context.sessions() as db:
        current = await db.get(Job, context.job_id)
        bound = next(item for item in current.result['taskItems'] if item['id'] == second['taskItemId'])
    replay = await execute(context, step=2, action='create_work', changes=changes, **next_arguments)
    assert replay.get('id') == second['id'], replay
    if relation == 'same_source_copy':
        observed = context.intent_model.inputs[-1]['conversationTask']['previousTask']['items']
        assert next(item for item in observed if item['id'] == bound['id']) == bound
    async with context.sessions() as db:
        from sqlalchemy import select
        from app.modules.operations.models import BusinessAction
        rows = (await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == context.owner_id))).all()
        assert len(rows) == (1 if relation == 'same_source_copy' else 2)
        assert all(row.task_id == sent['messageId'] for row in rows)
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert {work['id'] for work in works} == {first['objectId'], second['objectId']}
    assert all(work['revision'] == 1 for work in works)


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'status': 'done'}, {'nextStep': '约定验收'}])
async def test_continuation_separates_successful_work_property_receipts(setup, changes):
    work = await create(setup[3]['employee'], '原始标题')
    context, _ = await runtime(setup, '先改标题，再继续处理其他工作属性')
    await read_work(context, work['id'])
    first = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1,
                          changes={'title': '修订标题'})
    assert first['state'] == 'succeeded'
    await close_task(context, state='needs_input')
    context, _ = await runtime(setup, '继续修改状态和下一步，不重复改标题')
    context.intent_model = ScopedJudge(resume=True)
    await read_work(context, work['id'])
    arguments = dict(step=1, action='update_work', target_id=work['id'], expected_revision=2, changes=changes)
    wrong = await execute(context, **arguments, task_item_id=first['taskItemId'])
    assert wrong['state'] == 'failed' and '字段' in wrong['message']
    second = await execute(context, **arguments)
    assert second['state'] == 'succeeded' and second['id'] != first['id']
    assert second['taskItemId'] != first['taskItemId']
    saved = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['title'] == '修订标题' and saved['revision'] == 3
    assert all(saved[name] == value for name, value in changes.items())


@pytest.mark.asyncio
async def test_bind_validates_local_explicit_reference_and_report_submission_identity(monkeypatch):
    class Sessions:
        @asynccontextmanager
        async def begin(self):
            yield None

    original = {'action': 'generate_report', 'kind': 'weekly', 'date': '2026-10-10', 'submitAfter': False}
    old = {'id': 'old', 'action': 'generate_report', 'state': 'running', 'receiptId': 'receipt',
           'proposal': digest(original), 'attemptedOperation': original}
    job = SimpleNamespace(result={'taskItems': [old], 'taskSnapshot': {'previousTask': {'items': [old]}}})
    context = SimpleNamespace(sessions=Sessions(), task_item_keys={})

    async def lease(db, context):
        return job, None

    monkeypatch.setattr('app.tasks.lease.lease', lease)
    assert await bind(context, original, item_id='unknown')
    assert not context.task_item_keys and job.result['taskItems'] == [old]
    changed = {**original, 'submitAfter': True}
    assert await bind(context, changed, continuing=True, item_id='old')
    assert not await bind(context, changed, continuing=True)
    new_id = context.task_item_keys[digest(changed)]
    assert new_id != 'old'
    bound = next(item for item in job.result['taskItems'] if item['id'] == new_id)
    assert bound['attemptedOperation']['submitAfter'] is True and not bound.get('receiptId')
    assert not await bind(context, original, continuing=True)
    assert context.task_item_keys[digest(original)] == 'old'


def test_failed_work_can_correct_fields_and_report_can_add_submission():
    original = {'action': 'update_work', 'targetId': 'work', 'changes': {'title': '标题', 'status': 'done'}}
    failed = {'id': 'failed', 'action': 'update_work', 'targetId': 'work', 'state': 'failed',
              'workScope': ['properties'], 'attemptedOperation': original}
    assert not reference_error([failed], 'failed', {**original, 'changes': {'title': '标题'}})
    assert not reference_error([failed], 'failed', {**original, 'changes': {**original['changes'], 'nextStep': '补齐下一步'}})
    report = {'action': 'generate_report', 'submitAfter': False}
    failed = {'id': 'failed', 'action': 'generate_report', 'state': 'failed', 'attemptedOperation': report}
    assert not reference_error([failed], 'failed', {**report, 'submitAfter': True})


@pytest.mark.asyncio
@pytest.mark.parametrize('submit_after', [False, True])
async def test_legacy_report_binding_recovers_submission_identity_from_owned_receipt(setup, submit_after):
    work = await create(setup[3]['employee'], '报告来源', summary='已有确认进展')
    # Keep the source inside the fixed report period, independent of today's date.
    source_time = datetime(2026, 10, 10, 4, tzinfo=timezone.utc)
    async with setup[1].begin() as db:
        for model in (WorkRevision, WorkUpdate):
            await db.execute(update(model).where(model.work_id == work['id']).values(created_at=source_time))
    context, _ = await mode_runtime(setup, 'full', '生成周报，并按照要求处理提交')
    result = await execute(context, step=1, action='generate_report', report_date=source_time.date().isoformat(), submit_after=submit_after)
    assert result['state'] == 'running'
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        old = next(item for item in job.result['taskItems'] if item['id'] == result['taskItemId'])
        original = old['attemptedOperation']
        job.result = {**job.result, 'taskItems': [{key: value for key, value in old.items() if key != 'attemptedOperation'}]}
    assert not await bind(context, original, item_id=result['taskItemId'])
    assert context.task_item_keys[digest(original)] == result['taskItemId']
    assert await bind(context, {**original, 'submitAfter': not submit_after}, item_id=result['taskItemId'])
    async with context.sessions() as db:
        item = (await db.get(Job, context.job_id)).result['taskItems'][0]
        assert item['receiptId'] == result['id'] and item['attemptedOperation']['submitAfter'] is submit_after


@pytest.mark.asyncio
async def test_malformed_create_recovery_binds_server_item_before_authorization(setup):
    context, _ = await mode_runtime(setup, 'full', '随机创建一个工作，另建一个同名副本')
    context.intent_model = Judge()
    bad = {'title': '资料整理', 'bodyEdits': [{'action': 'append', 'blocks': [
        {'action': 'append_checklist', 'items': [{'text': '整理归档'}]}]}]}
    failed = await execute(context, step=1, action='create_work', changes=bad)
    assert failed['state'] == 'failed' and failed['taskItemId'] and not context.intent_model.inputs
    second = await execute(context, step=2, action='create_work', changes={'title': '资料整理'}, copy_index=2)
    assert second['state'] == 'succeeded' and second['taskItemId'] != failed['taskItemId']
    assert 'failedItemCandidates' not in context.intent_model.inputs[0]
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        assert task.result['operationFeedback']
    context.intent_model = RecoveryJudge(failed['taskItemId'])
    fixed = await execute(context, step=1, action='create_work', changes={'title': '资料整理', 'body': body('整理资料并记录索引')})
    assert fixed['state'] == 'succeeded' and fixed['taskItemId'] == failed['taskItemId']
    assert len(context.intent_model.inputs) == 1
    candidate = context.intent_model.inputs[0]['failedItemCandidates'][0]
    assert candidate['attemptedOperation']['changes'] == bad
    assert candidate['userSource']['userText'] == '随机创建一个工作，另建一个同名副本'
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert not task.result['operationFeedback'] and derive(task, [fixed, second])['state'] == 'completed'
        bound = next(item for item in task.result['taskItems'] if item['id'] == failed['taskItemId'])
        assert bound['receiptId'] == fixed['id'] and bound['state'] == 'succeeded'
        from app.tasks.nodes.node_state import node_dtos, release_outputs
        original = {'id': 'first-attempt', 'scope': 'current', 'kind': 'tool', 'label': '创建工作',
                    'state': 'failed', 'attempts': 1, 'errorCode': 'invalid_arguments',
                    'error': '参数不正确', 'output': {'name': 'execute_business_action', 'content': json.dumps(failed)}}
        unrelated = {**original, 'id': 'unrelated', 'output': {'name': 'execute_business_action',
                     'content': json.dumps({**failed, 'taskItemId': 'another-item'})}}
        task.result = {**task.result, 'nodeExecution': {'scope': 'current', 'nodes': [original, unrelated]}}
        recovered, other = node_dtos(task)
        assert recovered['state'] == 'succeeded' and recovered['label'] == '创建工作（已恢复）' and not recovered['error']
        assert other['state'] == 'failed' and original['state'] == 'failed'
        # The durable identity survives raw-output cleanup, but a completed
        # model interpretation or an unrelated receipt never proves recovery.
        release_outputs(task)
        assert node_dtos(task)[0]['state'] == 'succeeded'
        assert task.result['nodeExecution']['nodes'][0]['errorCode'] == 'invalid_arguments'
        actual_outcomes = task.result['toolOutcomes']
        task.result = {**task.result, 'toolOutcomes': [{**item, 'receiptId': 'unrelated'} for item in actual_outcomes]}
        assert node_dtos(task)[0]['state'] == 'failed'
        task.result = {**task.result, 'toolOutcomes': [*actual_outcomes,
                       {'taskItemId': failed['taskItemId'], 'category': 'invalid_arguments'}]}
        assert node_dtos(task)[0]['state'] == 'failed'


@pytest.mark.asyncio
async def test_invalid_parameters_after_authorization_reuse_existing_binding(setup, monkeypatch):
    context, _ = await mode_runtime(setup, 'full', '创建一项资料整理工作')
    async def invalid_write(*args, **kwargs):
        raise ValueError('invalid content after authorization')
    monkeypatch.setattr('app.agent.actions.operations.perform', invalid_write)
    result = await execute(context, step=1, action='create_work', changes={'title': '资料整理'})
    assert result['state'] == 'failed' and result['taskItemId']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert len(job.result['taskItems']) == 1
        assert job.result['taskItems'][0]['id'] == result['taskItemId']
        assert not job.result['taskItems'][0].get('receiptId')


def test_recovery_candidates_never_swap_shared_attachment_sources():
    original = {'action': 'create_work', 'changes': {'title': '同名资料'}, 'sharedAttachmentIds': ['source-a']}
    item = {'id': 'item', 'action': 'create_work', 'attemptedOperation': original}
    assert reference_error([item], 'item', {**original, 'sharedAttachmentIds': ['source-b']})


@pytest.mark.asyncio
async def test_same_step_and_title_new_create_does_not_clear_malformed_attempt(setup):
    context, _ = await mode_runtime(setup, 'full', '为两项独立方案分别建立工作')
    bad = {'title': '同名方案', 'bodyEdits': [{'action': 'append', 'blocks': [
        {'action': 'append_checklist', 'items': [{'text': '甲方案内容'}]}]}]}
    failed = await execute(context, step=1, action='create_work', changes=bad)
    context.intent_model = Judge()
    other = await execute(context, step=1, action='create_work', changes={'title': '同名方案', 'body': body('乙方案内容')})
    assert other['state'] == 'succeeded' and other['taskItemId'] != failed['taskItemId']
    assert context.intent_model.inputs[0]['failedItemCandidates'][0]['id'] == failed['taskItemId']
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert task.result['operationFeedback'] and derive(task, [other])['state'] == 'partial'


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit_final_id', [True, False])
async def test_multiple_malformed_create_attempts_share_checked_recovery(setup, explicit_final_id):
    context, _ = await mode_runtime(setup, 'full', '创建一项资料整理工作，正文写整理资料并记录索引')
    first_changes = {'title': '资料整理', 'bodyEdits': [{'action': 'append', 'blocks': [
        {'action': 'append_checklist', 'items': [{'text': '整理归档'}]}]}]}
    second_changes = {'title': '资料整理', 'body': {
        'schemaVersion': 1, 'content': [{'type': 'paragraph', 'content': '整理资料并记录索引'}]}}
    first = await execute(context, step=1, action='create_work', changes=first_changes)
    second = await execute(context, step=1, action='create_work', task_item_id=first['taskItemId'], changes=second_changes)
    assert first['state'] == second['state'] == 'failed'
    assert first['taskItemId'] == second['taskItemId'] and not context.intent_model.inputs
    context.intent_model = RecoveryJudge(first['taskItemId'])
    saved = await execute(context, step=1, action='create_work',
                          task_item_id=first['taskItemId'] if explicit_final_id else '',
                          changes={'title': '资料整理', 'body': body('整理资料并记录索引')})
    assert saved['state'] == 'succeeded' and saved['taskItemId'] == first['taskItemId']
    assert len(context.intent_model.inputs) == 1
    candidate = context.intent_model.inputs[0]['failedItemCandidates'][0]
    assert candidate['attemptedOperation']['changes'] == first_changes
    assert [attempt['changes'] for attempt in candidate['invalidAttempts']] == [first_changes, second_changes]
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert len(task.result['taskItems']) == 1
        assert task.result['taskItems'][0]['receiptId'] == saved['id']
        assert not task.result['operationFeedback'] and derive(task, [saved])['state'] == 'completed'
        from app.tasks.nodes.node_state import node_dtos, release_outputs
        task.result = {**task.result, 'nodeExecution': {'scope': 'current', 'nodes': [
            {'id': str(index), 'scope': 'current', 'kind': 'tool', 'label': '创建工作',
             'state': 'failed', 'attempts': 1, 'errorCode': 'invalid_arguments', 'error': '原始参数错误',
             'output': {'name': 'execute_business_action', 'content': json.dumps(result)}}
            for index, result in enumerate([first, second])]}}
        release_outputs(task)
        assert all(node['state'] == 'succeeded' for node in node_dtos(task))
        assert all(node['state'] == 'failed' and node['error'] == '原始参数错误'
                   for node in task.result['nodeExecution']['nodes'])
    assert len((await setup[3]['employee'].get('/api/v1/work-items')).json()['items']) == 1


@pytest.mark.asyncio
async def test_malformed_continuation_keeps_different_content_for_authorization(setup):
    context, _ = await mode_runtime(setup, 'full', '创建两项同名工作，一项整理资料，一项安排会议；分别保存完整正文')
    changes = {'title': '同名工作', 'body': {'schemaVersion': 1, 'content': '整理资料'}}
    first = await execute(context, step=1, action='create_work', changes=changes)
    other_changes = {**changes, 'body': {'schemaVersion': 1, 'content': '安排会议'}}
    second = await execute(context, step=1, action='create_work', task_item_id=first['taskItemId'], changes=other_changes)
    assert second['taskItemId'] == first['taskItemId']
    # A claimed chain is not proof of one request. The existing authorization
    # must see both incompatible contents and may refuse the attempted merge.
    context.intent_model = Judge(False)
    denied = await execute(context, step=1, action='create_work', task_item_id=first['taskItemId'],
                           changes={'title': '同名工作', 'body': body('安排会议')})
    assert denied['state'] == 'failed'
    claimed = context.intent_model.inputs[0]['recoveringItem']
    assert [attempt['changes'] for attempt in claimed['invalidAttempts']] == [changes, other_changes]
    assert not (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    context.intent_model = Judge()
    separate = await execute(context, step=2, action='create_work', changes={'title': '同名工作', 'body': body('完整安排会议')})
    assert separate['state'] == 'succeeded' and separate['taskItemId'] != first['taskItemId']
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        task.state = 'succeeded'
        assert derive(task, [separate])['state'] == 'partial'
        assert any(item['taskItemId'] == first['taskItemId'] for item in task.result['toolOutcomes'])


@pytest.mark.asyncio
@pytest.mark.parametrize(('first_args', 'next_args'), [
    ({}, {'task_item_id': 'unknown'}),
    ({}, {'copy_index': 2}),
    ({'target_id': 'first-target'}, {'target_id': 'other-target'}),
    ({'source_tokens': ['first-source']}, {'source_tokens': ['other-source']}),
    ({'shared_attachment_ids': ['first-file']}, {'shared_attachment_ids': ['other-file']}),
    ({'deliverable_id': 'plan', 'deliverable_revision': 1, 'item_id': 'first-entry'},
     {'deliverable_id': 'plan', 'deliverable_revision': 1, 'item_id': 'other-entry'}),
])
async def test_malformed_continuation_does_not_merge_other_identity(setup, first_args, next_args):
    context, _ = await mode_runtime(setup, 'full', '分别创建两项独立工作')
    changes = {'title': '同名工作', 'body': {'schemaVersion': 1, 'content': '无效格式'}}
    first = await execute(context, step=1, action='create_work', changes=changes, **first_args)
    second = await execute(context, step=1, action='create_work', changes={**changes, 'title': '修正提案'},
                           **{'task_item_id': first['taskItemId'], **next_args})
    assert first['state'] == second['state'] == 'failed'
    assert second['taskItemId'] != first['taskItemId']
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        assert len(task.result['taskItems']) == 2
        assert all(not item.get('invalidAttempts') for item in task.result['taskItems'])
    assert not context.intent_model.inputs


@pytest.mark.asyncio
async def test_malformed_continuation_bound_preserves_all_attempts_and_successful_items(setup):
    context, _ = await mode_runtime(setup, 'full', '创建一项工作')
    changes = {'title': '工作', 'body': {'schemaVersion': 1, 'content': '无效格式'}}
    first = await execute(context, step=1, action='create_work', changes=changes)
    for index in range(1, 9):
        result = await execute(context, step=1, action='create_work', task_item_id=first['taskItemId'],
                               changes={**changes, 'title': f'工作纠正 {index}'})
        assert (result['taskItemId'] == first['taskItemId']) is (index < 8)
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        original = next(item for item in task.result['taskItems'] if item['id'] == first['taskItemId'])
        assert len(original['invalidAttempts']) == 8
        assert original['invalidAttempts'][0]['changes'] == changes
        assert len(task.result['taskItems']) == 2 and len(task.result['toolOutcomes']) == 9
    context.intent_model = Judge()
    saved = await execute(context, step=2, action='create_work', changes={'title': '独立工作'})
    rejected = await execute(context, step=3, action='create_work', task_item_id=saved['taskItemId'],
                             changes={**changes, 'title': '另一份错误提案'})
    assert rejected['taskItemId'] != saved['taskItemId']
    async with context.sessions() as db:
        task = await db.get(Job, context.job_id)
        completed = next(item for item in task.result['taskItems'] if item['id'] == saved['taskItemId'])
        assert completed['receiptId'] == saved['id'] and completed['state'] == 'succeeded'
        assert not completed.get('invalidAttempts')


def test_malformed_chain_checks_sources_from_every_attempt():
    original = {'action': 'create_work', 'changes': {'title': '工作'}}
    with_source = {**original, 'sourceTokens': ['first-source']}
    item = {'id': 'item', 'action': 'create_work', 'attemptedOperation': original,
            'invalidAttempts': [original, with_source]}
    assert not reference_error([item], 'item', with_source)
    assert reference_error([item], 'item', original)
    assert reference_error([item], 'item', {**original, 'sourceTokens': ['another-source']})
