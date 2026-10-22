"""A corrected prerequisite gets a fresh decision, never implicit permission."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.agent.actions.operations import execute
from app.agent.actions.task_outcomes import authorization_evidence
from app.agent.tools.business.work import find_work_items
from app.core.digests import digest
from app.modules.deliverables.models import Deliverable
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from _support.agent.business_actions import Judge
from _support.agent.conversation_task_state import ScopedJudge
from _support.materials.deliverables import read_plan, save_plan
from _support.agent.execution_permissions import mode_runtime

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(('first_kind', 'latest_kind'), [
    ('not_requested', 'missing_info'),
    ('missing_info', 'not_requested'),
    ('not_requested', 'success'),
    ('not_requested', 'invalid_source'),
    ('not_requested', 'invalid_item'),
])
async def test_new_evidence_replaces_only_current_proposal_classification(setup, first_kind, latest_kind):
    _, sessions, users, _ = setup
    context, _ = await mode_runtime(setup, 'full', '先查看我的工作，然后创建一项新工作')
    context.node_retry = True
    await initialize(context, 'classification-after-new-evidence')

    class Verdict:
        def __init__(self):
            self.inputs = []

        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            self.inputs.append(payload)
            kind = first_kind if len(self.inputs) == 1 else latest_kind
            return AIMessage(content=json.dumps({
                'allowed': kind in ('success', 'invalid_source', 'invalid_item'),
                'quote': '并不存在的用户授权' if kind == 'invalid_source' else payload['currentUserText'],
                'reason': kind, 'notRequested': kind == 'not_requested',
                'failureKind': kind if kind in ('missing_info', 'not_requested') else 'invalid_arguments',
                'recoveryOwner': 'user' if kind == 'missing_info' else 'assistant',
                'missingInputs': [{'field': 'target', 'question': '保存到哪项工作？',
                                   'unavailableFromSources': '用户尚未指定保存位置', 'candidateIds': []}] if kind == 'missing_info' else [],
                'taskItemId': 'unknown-item' if kind == 'invalid_item' else '',
            }))

    judge = Verdict()
    context.intent_model = judge
    other_key = digest({'action': 'delete_work', 'targetId': 'another-proposal'})
    context.authorization_outcomes[other_key] = 'not_requested'
    context.unrequested_actions.add(other_key)
    args = {'step': 1, 'action': 'create_work', 'changes': {'title': '新工作'}}
    first = await execute(context, **args)
    assert first['state'] == ('not_requested' if first_kind == 'not_requested' else 'waiting')
    await find_work_items.coroutine('', SimpleNamespace(context=context))
    latest = await execute(context, **args)
    assert len(judge.inputs) == 2
    key = digest(judge.inputs[-1]['proposedOperation'])
    category = 'invalid_arguments' if latest_kind.startswith('invalid_') else latest_kind
    expected_state = {'success': 'succeeded', 'not_requested': 'not_requested',
                      'missing_info': 'waiting', 'invalid_arguments': 'failed'}[category]
    assert latest['state'] == expected_state, latest
    if expected_state in ('waiting', 'failed'):
        assert latest['category'] == category
    assert context.authorization_outcomes[key] == category
    assert (key in context.unrequested_actions) == (category == 'not_requested')

    if expected_state != 'succeeded':
        # A cache hit must restore the current classification, including when
        # this worker still holds the opposite marker from another attempt.
        if category == 'not_requested':
            context.unrequested_actions.discard(key)
        else:
            context.unrequested_actions.add(key)
        assert (await execute(context, **args)) == latest
        assert len(judge.inputs) == 2
        assert (key in context.unrequested_actions) == (category == 'not_requested')
    assert context.authorization_outcomes[other_key] == 'not_requested'
    assert other_key in context.unrequested_actions
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == int(expected_state == 'succeeded')


async def test_evidence_ignores_timestamps_repeated_reads_and_model_interpretations():
    request = {'currentUserText': '加入前两项', 'privateDeliverables': {'items': [{'id': 'a', 'revision': 1, 'updatedAt': 'before'}]},
               'completedOrPendingSteps': [], 'verifiedReads': {'teamQueries': [{'query': 'actual'}]}}
    before = authorization_evidence(request)
    request['privateDeliverables']['items'][0]['updatedAt'] = 'after'
    request['verifiedReads']['teamQueries'] *= 2
    request['proposedOperation'] = {'changes': {'title': 'model rewrite'}}
    request['conversationTask'] = {'remaining': ['new model interpretation']}
    assert authorization_evidence(request) == before
    request['privateDeliverables']['items'][0]['revision'] = 2
    assert authorization_evidence(request) != before


async def test_corrected_reference_resolves_only_the_exact_unlinked_effect():
    from app.tasks.feedback.outcomes import record
    job = SimpleNamespace(result={})
    failed = {'state': 'clarification', 'category': 'missing_info', 'message': '缺少前置资料'}
    first = {'step': 1, 'changes': {'title': '甲'}}
    record(job, 'create_work', first, failed)
    record(job, 'create_work', {'step': 2, 'changes': {'title': '乙'}}, failed)
    record(job, 'create_work', {'step': 1, 'changes': {'title': '甲', 'summary': '不同内容'}}, failed)
    record(job, 'create_work', {**first, 'step': 3, 'deliverable_id': 'different', 'deliverable_revision': 1, 'item_id': 'other'}, failed)
    record(job, 'create_work', {**first, 'step': 5, 'copy_index': 2}, failed)
    record(job, 'create_work', {**first, 'step': 4, 'deliverable_id': 'validated', 'deliverable_revision': 1, 'item_id': 'selected'}, {'state': 'succeeded', 'id': 'receipt'})
    assert [(item['step'], item['category']) for item in job.result['toolOutcomes']] == [(2, 'missing_info'), (1, 'missing_info'), (3, 'missing_info'), (5, 'missing_info'), (4, 'success')]


async def test_saved_plan_rechecks_refusal_and_creates_exactly_two_linked_works(setup):
    _, sessions, users, _ = setup
    context, _ = await mode_runtime(setup, 'full', '把刚才计划的前两项分别创建为我的工作，不创建第三项。请直接保存。')
    context.node_retry = True
    await initialize(context, 'controlled-material-plan')
    judge = ScopedJudge(allowed=False, kind='missing_info')
    context.intent_model = judge
    first_args = {'step': 1, 'action': 'create_work', 'changes': {'title': '明确范围与技术方案', 'summary': '明确范围和技术方案'}}
    assert (await execute(context, **first_args))['state'] == 'waiting'
    assert (await execute(context, **first_args))['state'] == 'waiting'
    assert len(judge.inputs) == 1

    saved = await save_plan(context, title='实施计划', body='按顺序实施', items=[{'title': '明确范围与技术方案'}, {'title': '开发与联调'}, {'title': '验收'}])
    await read_plan(context, saved['id'])
    # Correcting one prerequisite still does not supply the required item.
    unresolved = await execute(context, **first_args)
    assert unresolved['state'] == 'waiting' and unresolved['taskItemId']
    assert len(judge.inputs) == 2
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 0

    class SelectedJudge(Judge):
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            selection = payload['proposedOperation']['deliverableSelection']
            assert selection['revision'] == 1 and len(selection['items']) == 1
            assert selection['items'][0]['id'] in {entry['id'] for entry in saved['items'][:2]}
            return await super().ainvoke(messages)
    fresh = SelectedJudge()
    context.intent_model = fresh
    reference = {'deliverable_id': saved['id'], 'deliverable_revision': 1}
    first = await execute(context, **{**first_args, 'step': 3}, **reference, item_id=saved['items'][0]['id'], task_item_id=unresolved['taskItemId'])
    second_args = {'step': 2, 'action': 'create_work', 'changes': {'title': '开发与联调', 'summary': '完成开发和联调'}, **reference, 'item_id': saved['items'][1]['id']}
    second = await execute(context, **second_args)
    assert first['state'] == second['state'] == 'succeeded'
    assert first['taskItemId'] == unresolved['taskItemId']
    assert (await execute(context, **{**second_args, 'step': 4}))['id'] == second['id']
    assert len(fresh.inputs) == 2
    read = await read_plan(context, saved['id'])
    assert {link['itemId'] for link in read['links']} == {entry['id'] for entry in saved['items'][:2]}
    async with sessions() as db:
        rows = (await db.scalars(select(WorkItem).where(WorkItem.owner_id == users['employee'].id))).all()
        assert len(rows) == 2
        assert sorted(work.content['summary'] for work in rows) == ['完成开发和联调', '明确范围和技术方案']
        job = await db.get(Job, context.job_id)
        assert not [item for item in job.result['toolOutcomes'] if item['category'] == 'missing_info']
        assert job.result['operationFeedback'] == []


@pytest.mark.parametrize('allowed', [True, False])
async def test_actual_read_invalidates_cached_node_but_never_grants_permission(setup, allowed):
    _, sessions, users, _ = setup
    context, _ = await mode_runtime(setup, 'full', '先查看我的工作，然后创建新工作')
    context.node_retry = True
    await initialize(context, 'controlled-read-prerequisite')
    judge = ScopedJudge(allowed=False, kind='missing_info')
    context.intent_model = judge
    args = {'step': 1, 'action': 'create_work', 'changes': {'title': '新的工作'}}
    assert (await execute(context, **args))['state'] == 'waiting'
    await find_work_items.coroutine('', SimpleNamespace(context=context))
    judge.allowed = allowed
    result = await execute(context, **args)
    assert result['state'] == ('succeeded' if allowed else 'waiting')
    assert len(judge.inputs) == 2
    async with sessions() as db:
        count = await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id))
        assert count == int(allowed)


async def test_selected_item_refusals_do_not_block_siblings_or_bypass_read_and_revocation(setup):
    _, sessions, users, _ = setup
    context, _ = await mode_runtime(setup, 'full', '只把计划前两项加入工作，不创建第三项')
    saved = await save_plan(context, title='计划', body='三个条目', items=[{'title': title} for title in ('范围', '开发', '验收')])
    reference = {'deliverable_id': saved['id'], 'deliverable_revision': 1}
    denied = ScopedJudge(allowed=False, kind='not_requested')
    context.intent_model = denied
    third = await execute(context, step=3, action='create_work', changes={'title': '验收'}, **reference, item_id=saved['items'][2]['id'])
    assert third['state'] == 'not_requested'
    assert context.authorization_outcomes[digest(denied.inputs[-1]['proposedOperation'])] == 'not_requested'
    context.intent_model = Judge()
    first = await execute(context, step=1, action='create_work', changes={'title': '范围'}, **reference, item_id=saved['items'][0]['id'])
    assert first['state'] == 'succeeded'
    # A new receipt invalidates the old decision, not the user's restriction.
    context.intent_model = denied
    assert (await execute(context, step=3, action='create_work', changes={'title': '验收'}, **reference, item_id=saved['items'][2]['id']))['state'] == 'not_requested'
    assert len(denied.inputs) == 2
    forged = await execute(context, step=2, action='create_work', changes={'title': '开发'},
                           deliverable_id=str(uuid4()), deliverable_revision=1, item_id=saved['items'][1]['id'])
    assert forged['state'] == 'conflict' and len(denied.inputs) == 2
    async with sessions.begin() as db:
        source = await db.get(Deliverable, saved['id'])
        source.owner_id = users['peer'].id
    with pytest.raises(HTTPException):
        await execute(context, step=2, action='create_work', changes={'title': '开发'}, **reference, item_id=saved['items'][1]['id'])
    assert len(denied.inputs) == 2
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 1
