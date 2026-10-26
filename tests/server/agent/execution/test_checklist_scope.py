"""Checklist target scope is independent of the proposed write, without another model phase."""
import copy
import json

import pytest
from langchain_core.messages import AIMessage

from app.agent.actions.checklist_scope import ChecklistSelection, selection_issue, validate_selection
from app.agent.actions.operations import execute
from app.agent.actions.work_change_plan import ChecklistWorkChangePlan, FIELDS, WorkChangePlan, checklist_execution_plan, patch_error, plan_model, source_input, validate_plan, work_change_plan
from app.modules.work.content.checklist import checklist_items
from app.tasks.lease import lease
from _support.agent.assistant_execution import ReceiptJudge
from _support.agent.business_actions import read_work
from _support.agent.execution_permissions import mode_runtime
from _support.work.work_change_plan import PlanJudge
from _support.work.work_records import create


def grouped_body():
    nodes = []
    for heading in ('招聘', '报销'):
        nodes.extend([
            {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': heading}]},
            {'type': 'taskList', 'content': [{'type': 'taskItem', 'attrs': {'checked': False}, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '打印材料'}]}]}]},
        ])
    return {'schemaVersion': 1, 'content': nodes}


class SelectionJudge(PlanJudge):
    def __init__(self, state, targets, quote):
        super().__init__({'body': ('set', quote, None)} if state != 'not_requested' else {})
        self.state, self.targets, self.quote = state, targets, quote

    async def ainvoke(self, messages):
        response = await super().ainvoke(messages)
        result = json.loads(response.content)
        payload = self.inputs[-1]
        assert payload['checklistSelectionRequired']
        assert 'workContentChanges' not in payload and 'bodyEdits' not in payload
        result['checklistSelection'] = {'state': self.state, 'targets': self.targets, 'quotes': [{'text': self.quote, 'messageId': payload['messageId']}]}
        return AIMessage(content=json.dumps(result))


@pytest.mark.asyncio
@pytest.mark.parametrize('state,quote', [
    ('ambiguous', '把打印材料标记完成'),
    ('not_requested', '打印材料弄好了，先告诉你一下，不用记录'),
])
async def test_ambiguous_or_unrequested_check_never_writes_even_when_proposal_selects_both(setup, state, quote):
    work = await create(setup[3]['employee'], body=grouped_body())
    context, _ = await mode_runtime(setup, 'full', quote)
    read = await read_work(context, work['id'])
    ids = list(checklist_items(read['body']))
    context.work_change_model = SelectionJudge(state, [], quote)
    context.intent_model = ReceiptJudge(requested_changes=[{'field': 'body', 'kind': 'content', 'quote': quote}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    for selected in (ids, ids[:1]):
        result = await execute(context, **args, changes={'bodyEdits': [{'action': 'set_checked', 'itemId': item, 'checked': True} for item in selected]})
        assert result['category'] == ('missing_info' if state == 'ambiguous' else 'invalid_arguments'), result
    latest = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert latest['revision'] == 1 and latest['body'] == work['body']
    assert len(context.work_change_model.inputs) == 1
    assert not context.intent_model.inputs


@pytest.mark.asyncio
@pytest.mark.parametrize('count,quote', [
    (1, '把招聘里的打印材料标记完成，报销的不改'),
    (2, '把招聘和报销两处打印材料都标记完成'),
])
async def test_exact_single_or_batch_scope_rejects_extra_missing_and_opposite_targets(setup, count, quote):
    work = await create(setup[3]['employee'], body=grouped_body())
    context, _ = await mode_runtime(setup, 'full', quote)
    read = await read_work(context, work['id'])
    ids = list(checklist_items(read['body']))
    targets = [{'itemId': item, 'checked': True} for item in ids[:count]]
    context.work_change_model = SelectionJudge('resolved', targets, quote)
    context.intent_model = ReceiptJudge(requested_changes=[{'field': 'body', 'kind': 'content', 'quote': quote}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    wrong_targets = [{'itemId': item, 'checked': True} for item in (ids if count == 1 else ids[:1])]
    for proposed in (wrong_targets, [{**target, 'checked': False} for target in targets]):
        result = await execute(context, **args, changes={'bodyEdits': [{'action': 'set_checked', **target} for target in proposed]})
        assert result['category'] == 'invalid_arguments', result
    changes = {'bodyEdits': [{'action': 'set_checked', **target} for target in targets]}
    result = await execute(context, **args, changes=changes)
    assert result['state'] == 'succeeded', result
    assert (await execute(context, **args, changes=changes))['id'] == result['id']
    latest = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert latest['revision'] == 2 and latest['status'] == 'in_progress'
    assert [item['attrs']['checked'] for item in checklist_items(latest['body']).values()] == ([True, False] if count == 1 else [True, True])
    assert len(context.work_change_model.inputs) == len(context.intent_model.inputs) == 1


@pytest.mark.asyncio
async def test_resolved_selection_with_preserved_body_uses_one_scope_call_and_keeps_raw_cache(setup):
    quote = '把招聘里的打印材料标记完成，报销的不改'
    work = await create(setup[3]['employee'], body=grouped_body())
    context, _ = await mode_runtime(setup, 'full', quote)
    read = await read_work(context, work['id'])
    target = next(iter(checklist_items(read['body'])))
    class PreservedBodyJudge(SelectionJudge):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            result = json.loads(response.content)
            result['changed'] = [item for item in result['changed'] if item['field'] != 'body']
            result['preserved'].append('body')
            return AIMessage(content=json.dumps(result))
    context.work_change_model = PreservedBodyJudge('resolved', [{'itemId': target, 'checked': True}], quote)
    context.intent_model = ReceiptJudge(requested_changes=[{'field': 'body', 'kind': 'content', 'quote': quote}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    mismatch = await execute(context, **args, changes={'bodyEdits': [{'action': 'set_checked', 'itemId': target, 'checked': False}]})
    assert mismatch['category'] == 'invalid_arguments'
    saved = await execute(context, **args, changes={'bodyEdits': [{'action': 'set_checked', 'itemId': target, 'checked': True}]})
    assert saved['state'] == 'succeeded', saved
    assert len(context.work_change_model.inputs) == len(context.intent_model.inputs) == 1
    async with context.sessions() as db:
        job, _ = await lease(db, context)
        cached = list(job.result['workChangePlans'].values())
        assert len(cached) == 1 and cached[0]['body']['mode'] == 'preserve'
        assert cached[0]['checklistSelection']['targets'] == [{'itemId': target, 'checked': True}]
        assert not job.result.get('workChangePlanRepairs')
    authorized = context.intent_model.inputs[0]['workChangePlan']
    field = next(item for item in authorized['changed'] if item['field'] == 'body')
    assert field['mode'] == 'set'
    assert field['quotes'] == authorized['checklistSelection']['quotes']


@pytest.mark.asyncio
async def test_cached_item_scope_does_not_authorize_later_mixed_or_whole_body_patch(setup):
    quote = '把招聘里的打印材料标记完成，报销的不改'
    work = await create(setup[3]['employee'], body=grouped_body())
    context, sent = await mode_runtime(setup, 'full', quote)
    read = await read_work(context, work['id'])
    target = next(iter(checklist_items(read['body'])))
    judge = SelectionJudge('resolved', [{'itemId': target, 'checked': True}], quote)
    judge.fields = {}
    request = {'currentUserText': quote, 'conversationTask': {}, 'conversationForReferenceOnly': [], 'messageTime': '', 'timezone': 'Asia/Shanghai'}
    edit = {'action': 'set_checked', 'itemId': target, 'checked': True}
    proposal = {'action': 'update_work', 'targetId': work['id'], 'expectedRevision': 1, 'targetContent': read, 'changes': {'bodyEdits': [edit]}}
    initial = await work_change_plan(context, request, proposal, sent['messageId'], judge)
    assert initial.body.mode == 'set' and len(judge.inputs) == 1
    mixed = {**proposal, 'changes': {'bodyEdits': [edit, {'action': 'append_checklist', 'items': [{'text': '额外事项'}]}]}}
    resolved = await work_change_plan(context, request, mixed, sent['messageId'], judge)
    assert resolved.body.mode == 'preserve' and patch_error(resolved, mixed)
    assert len(judge.inputs) == 2  # Existing bounded conflict repair, not a new checklist stage.
    async with context.sessions() as db:
        job, _ = await lease(db, context)
        caches = list(job.result['workChangePlans'].values())
        assert len(caches) == 1 and caches[0]['body']['mode'] == 'preserve'
    cached_plan = ChecklistWorkChangePlan.model_validate(caches[0])
    for changes in (
        mixed['changes'],
        {'body': {'schemaVersion': 1, 'content': []}},
        {'bodyEdits': [edit], 'title': '额外标题'},
    ):
        later = {**proposal, 'changes': changes}
        assert checklist_execution_plan(cached_plan, later) is cached_plan
        assert patch_error(cached_plan, later)
    exact_again = await work_change_plan(context, request, proposal, sent['messageId'], judge)
    assert exact_again.body.mode == 'set' and len(judge.inputs) == 2
    latest = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert latest['revision'] == 1 and latest['body'] == work['body']


def test_selection_is_conditionally_typed_and_rejects_forged_scope():
    from app.modules.work.content.document import WorkDocument
    doc = WorkDocument.model_validate(grouped_body()).model_dump()
    ids = list(checklist_items(doc))
    request = {'currentUserText': '把招聘里的打印材料标记完成', 'conversationTask': {}, 'conversationForReferenceOnly': [], 'messageTime': '', 'timezone': 'Asia/Shanghai'}
    proposal = {'targetId': 'work', 'targetContent': {'body': doc}, 'changes': {'bodyEdits': [{'action': 'set_checked', 'itemId': ids[0], 'checked': True}]}}
    payload = source_input(request, proposal, 'current')
    other = source_input(request, {**proposal, 'changes': {'bodyEdits': [{'action': 'append_checklist', 'items': [{'text': '新增'}]}]}}, 'current')
    assert plan_model(payload) is ChecklistWorkChangePlan and plan_model(other) is WorkChangePlan
    assert 'checklistSelection' not in WorkChangePlan.model_json_schema()['properties']
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    fields['body'] = {'mode': 'set', 'quotes': [{'text': request['currentUserText']}], 'value': None}
    selection = {'state': 'resolved', 'targets': [{'itemId': ids[0], 'checked': True}], 'quotes': [{'text': request['currentUserText']}]}
    plan = validate_plan(ChecklistWorkChangePlan.model_validate({**fields, 'checklistSelection': selection}), payload)
    assert selection_issue(plan, proposal) is None
    for patch in (
        {'targets': [{'itemId': 'foreign', 'checked': True}]},
        {'targets': selection['targets'] * 2},
        {'state': 'ambiguous'},
        {'quotes': [{'text': '同时完成全部'}]},
        {'quotes': []},
    ):
        with pytest.raises(ValueError):
            validate_selection(ChecklistSelection.model_validate({**copy.deepcopy(selection), **patch}), payload)
