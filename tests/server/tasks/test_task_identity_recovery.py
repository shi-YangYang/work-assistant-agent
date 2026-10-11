"""Same-task recovery must use checked identities, not rewritten arguments."""
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
    assert guessed['state'] == 'clarification' and guessed['taskItemId'] == first['taskItemId']
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
    replay = await execute(context, step=2, action='create_work', changes=changes, **next_arguments)
    assert replay['id'] == second['id']
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

    original = {'action': 'generate_report', 'kind': 'daily', 'date': '2026-10-10', 'submitAfter': False}
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
    context, _ = await mode_runtime(setup, 'full', '生成日报，并按照要求处理提交')
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
