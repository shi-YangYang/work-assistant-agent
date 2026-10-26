"""Keep historical wire parsing and replay material evidence under the current plan contract."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.agent.actions.intent import WorkIntentVerdict, destination_gap_precedes_fields, schema_feedback
from app.agent.actions.material_selection import issue, normalize_contract, resolve
from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan
from app.agent.runtime.model import BoundedChatModel
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem, WorkMaterial
from app.tasks.feedback.public import job_error, node_error, prose
from app.tasks.models import Job
from app.tasks.processing import handlers
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import create
from _support.agent.execution_permissions import set_mode
from _support.http.company import keyed


RESPONSES = json.loads((Path(__file__).parents[1] / '_support/agent/material_authorization_responses.json').read_text())
GAP_RESPONSES = json.loads((Path(__file__).parents[1] / '_support/agent/material_authorization_gap_responses.json').read_text())
CLARIFICATION_RESPONSE = json.loads((Path(__file__).parents[1] / '_support/agent/authorization_clarification_response.json').read_text())
TEXT = RESPONSES[0]['quote']
MESSAGE = RESPONSES[0]['materialSelection']['messageId']
WORK = RESPONSES[0]['materialSelection']['targetId']


def planned_material_wire(recorded):
    """Project only superseded scope fields; preserve raw evidence and other defects.

    This is a fixed test projection, not a new captured model response. The
    independent compact plan now provides requested fields and their quotes.
    """
    return {**{key: copy.deepcopy(value) for key, value in recorded.items()
               if key not in ('requestedChanges', 'requiredFields', 'appendFields')},
            'invalidFields': []}


def request():
    return {'messageId': MESSAGE, 'currentUserText': TEXT,
        'conversationTask': {'workReference': {'id': WORK, 'revision': 1}},
        'privateDeliverables': {'collectionComplete': True, 'items': [
            {'files': [{'materialSource': source}]} for source in RESPONSES[1]['materialSelection']['references']]},
        'proposedOperation': {'action': 'update_work', 'targetId': WORK}}


@pytest.mark.parametrize('index', range(4))
def test_actual_wire_variants_normalize_without_changing_authorization(index):
    original = copy.deepcopy(RESPONSES[index])
    normalized = normalize_contract(original, request())
    assert {k: v for k, v in normalized.items() if k != 'materialSelection'} == {
        k: v for k, v in original.items() if k != 'materialSelection'}
    verdict = WorkIntentVerdict.model_validate(normalized)
    selected = resolve(verdict.materialSelection, request())
    assert selected['targetId'] == WORK and len(selected['sources']) == 11
    assert selected['destinationProof']['source'] == 'work_reference'
    assert original == RESPONSES[index]
    # This wire variant is syntactically recoverable, not semantically complete.
    if index == 3:
        assert verdict.requestedChanges == [] and verdict.requiredFields == []


@pytest.mark.parametrize('case', ['mode_conflict', 'message_conflict', 'evidence_message_conflict',
    'target_conflict', 'target_reference_conflict', 'no_reference', 'unavailable_reference',
    'stale_selection', 'stale_evidence', 'forged_selection_quote', 'forged_evidence_quote',
    'source_conflict', 'null_target', 'wrong_type_target', 'unknown_field'])
def test_wire_normalization_rejects_conflicts_and_never_borrows_other_targets(case):
    raw, payload = copy.deepcopy(RESPONSES[0]), request()
    selection, evidence = raw['materialSelection'], raw['materialSelection']['destinationEvidence']
    if case == 'mode_conflict':
        selection['mode'] = 'selected'
    elif case == 'message_conflict':
        selection['quoteMessageId'] = 'old-message'
    elif case == 'evidence_message_conflict':
        evidence['quoteMessageId'] = 'old-message'
    elif case == 'target_conflict':
        evidence['targetId'] = 'other'
    elif case == 'target_reference_conflict':
        selection['targetId'] = evidence['targetId'] = 'other'
    elif case == 'no_reference':
        payload['conversationTask'] = {'previousTask': {'workReference': {'id': WORK}}}
        payload['verifiedReads'] = {'ownWorkRead': [{'id': WORK, 'title': '唯一工作'}]}
    elif case == 'unavailable_reference':
        payload['conversationTask']['workReference']['unavailable'] = True
    elif case == 'stale_selection':
        selection['messageId'] = 'old-message'
    elif case == 'stale_evidence':
        evidence['messageId'] = 'old-message'
    elif case == 'forged_selection_quote':
        selection['quote'] = '没有说过的话'
    elif case == 'forged_evidence_quote':
        evidence['quote'] = '没有说过的话'
    elif case == 'source_conflict':
        evidence['source'] = 'user'
    elif case in ('null_target', 'wrong_type_target'):
        selection['targetId'] = evidence['targetId'] = None if case == 'null_target' else 123
    else:
        selection['authorizeEverything'] = True
    with pytest.raises(ValueError):
        verdict = WorkIntentVerdict.model_validate(normalize_contract(raw, payload))
        resolve(verdict.materialSelection, payload)


@pytest.mark.parametrize('destination', ['new', 'unselected'])
def test_reference_never_converts_another_destination(destination):
    raw, payload = copy.deepcopy(RESPONSES[2]), request()
    raw['materialSelection']['destination'] = destination
    value = WorkIntentVerdict.model_validate(normalize_contract(raw, payload)).materialSelection
    assert value.destination == destination and not value.targetId
    assert resolve(value, payload)['destination'] == 'unselected'
    raw['materialSelection']['destinationEvidence']['targetId'] = WORK
    with pytest.raises(ValueError):
        normalize_contract(raw, payload)


@pytest.mark.parametrize('raw', [{}, {'allowed': True}, {'allowed': False, 'reason': ''}, None, []])
def test_missing_whole_verdict_is_not_reconstructed(raw):
    with pytest.raises(ValueError):
        WorkIntentVerdict.model_validate(normalize_contract(raw, request()))


def test_restored_collection_target_cannot_be_rebound_by_current_reference():
    payload = request()
    selected = resolve(WorkIntentVerdict.model_validate(normalize_contract(RESPONSES[0], payload)).materialSelection, payload)
    payload['materialCollections'] = [selected]
    payload['conversationTask']['workReference'] = {'id': 'different'}
    raw = copy.deepcopy(RESPONSES[2])
    raw['materialSelection'].update(mode='previous', previousId=selected['id'])
    with pytest.raises(ValueError, match='同一工作'):
        resolve(WorkIntentVerdict.model_validate(normalize_contract(raw, payload)).materialSelection, payload)


def test_reference_recovery_does_not_authorize_a_different_proposed_target():
    payload = request()
    payload['proposedOperation']['targetId'] = 'another-work'
    verdict = WorkIntentVerdict.model_validate(normalize_contract(RESPONSES[2], payload))
    selected = resolve(verdict.materialSelection, payload)
    assert selected['targetId'] == WORK
    assert issue(selected, payload['proposedOperation'], []) == {
        'kind': 'invalid_arguments', 'field': 'target', 'code': 'target_mismatch'}


@pytest.mark.asyncio
@pytest.mark.parametrize('owner', ['peer', 'outsider'])
async def test_cross_account_reference_is_rejected_before_decoding(setup, owner):
    _, sessions, users, clients = setup
    work = await create(clients[owner], '资料整理')
    response = await clients['employee'].post('/api/v1/messages', json={
        'newConversation': True, 'text': TEXT, 'workReference': {'workId': work['id']}}, headers=keyed())
    assert response.status_code in (403, 404), response.text
    async with sessions() as db:
        assert not await db.scalar(select(Job.id).where(Job.owner_id == users['employee'].id))
        assert not await db.scalar(select(WorkMaterial.id).where(WorkMaterial.owner_id == users['employee'].id))


async def runtime(setup, *, text=TEXT, reference=True):
    settings, sessions, users, clients = setup
    await set_mode(clients['employee'], 'full')
    work = await create(clients['employee'], '资料整理', summary='原来的工作内容必须保留')
    await create(clients['employee'], '资料整理', summary='同名工作不可被修改')
    result = await clients['employee'].post('/api/v1/messages', json={
        'newConversation': True, 'text': text,
        **({'workReference': {'workId': work['id']}} if reference else {})}, headers=keyed())
    assert result.status_code == 202, result.text
    sent = result.json()
    job = await claim(sessions, users['employee'].id)
    values = []
    async with sessions.begin() as db:
        message = await db.get(Message, sent['messageId'])
        directory = settings.media_dir / 'generated'
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(11):
            data = f'material {i}'.encode()
            checksum = hashlib.sha256(data).hexdigest()
            (directory / checksum).write_bytes(data)
            item = Deliverable(company_id=job.company_id, owner_id=job.owner_id,
                conversation_id=message.conversation_id, title=f'文件 {i}', access=message.access)
            db.add(item)
            await db.flush()
            file_id = str(uuid4())
            db.add(DeliverableRevision(company_id=job.company_id, owner_id=job.owner_id,
                deliverable_id=item.id, revision=1, message_id=message.id, step=i + 1,
                title=item.title, body='受控文件', digest=checksum,
                files=[{'id': file_id, 'name': 'same.txt', 'mimeType': 'text/plain',
                    'size': len(data), 'sha256': checksum, 'storageKey': checksum, 'sources': []}]))
            values.append({'deliverableId': item.id, 'revision': 1, 'fileId': file_id})
        original = copy.deepcopy((await db.get(WorkItem, work['id'])).content)
    return job, sent, work, values, original


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', [0, 1, 2, 3, 'denied', 'scope-conflict'])
async def test_recorded_material_evidence_with_current_plan_preserves_authorization(setup, monkeypatch, variant):
    job, sent, work, values, original = await runtime(setup)
    settings, sessions, users, clients = setup
    index = 0 if isinstance(variant, str) else variant
    wire = json.dumps(RESPONSES[index], ensure_ascii=False).replace(MESSAGE, sent['messageId']).replace(WORK, work['id'])
    # Original files stay unchanged; rebind identities before the explicit projection.
    for old, new in zip(RESPONSES[1]['materialSelection']['references'], values):
        wire = wire.replace(old['deliverableId'], new['deliverableId']).replace(old['fileId'], new['fileId'])
    if variant == 'denied':
        refusal = json.loads(wire)
        refusal.update(allowed=False, failureKind='permission_denied', recoveryOwner='system', denialScope='authorization')
        wire = json.dumps(refusal, ensure_ascii=False)
    original_context = handlers.RunContext
    def with_plan(*args, **kwargs):
        result = original_context(*args, **kwargs)
        result.work_change_model = kwargs['intent_model']
        return result
    monkeypatch.setattr(handlers, 'RunContext', with_plan)

    class WireModel(BoundedChatModel):
        calls: int = 0
        plans: int = 0
        checks: int = 0
        repairs: list[str] = []
        async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
            payload = next((json.loads(m.content) for m in input if isinstance(m.content, str)
                and m.content.startswith('{') and ('"proposedOperation"' in m.content or '"work_change_plan"' in m.content)), {}) if isinstance(input, list) else {}
            if payload.get('task') == 'work_change_plan':
                self.plans += 1
                fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
                fields['materials'] = {'mode': 'set', 'value': None, 'quotes': [{'messageId': sent['messageId'], 'text': TEXT}]}
                return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(fields))))
            if payload.get('proposedOperation'):
                self.checks += 1
                reference = payload['conversationTask']['workReference']
                assert reference['id'] == work['id'] and not reference.get('unavailable')
                self.repairs.extend(m.content for m in input if isinstance(m.content, str) and m.content.startswith('本次核对输出须同时满足：'))
                projected = planned_material_wire(json.loads(wire))
                if variant == 'scope-conflict':
                    projected['invalidFields'] = ['materials']
                return AIMessage(content=json.dumps(projected, ensure_ascii=False))
            return await super().ainvoke(input, config, stop=stop, **kwargs)
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            steps = [('load_tools', {'groups': ['work']}), ('execute_business_action', {
                'step': 1, 'action': 'update_work', 'target_id': work['id'],
                'expected_revision': work['revision'], 'changes': {'materials': values}})]
            if self.calls > len(steps):
                assert variant == 'denied' and self.calls == 3
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content='你目前没有权限完成这项操作。'))])
            name, args = steps[self.calls - 1]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                'id': f'wire-{self.calls}', 'name': name, 'args': args}]))])

    model = WireModel(model='controlled-wire', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await handlers.process_job(job, sessions, settings, saver, model=model)
    public = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert not public['interactions']
    # Variant 3 omitted old scope lists, now supplied by the independent plan.
    # A contradictory current verdict remains a separate zero-write failure.
    success = variant in (0, 1, 2, 3)
    async with sessions() as db:
        current = await db.get(WorkItem, work['id'])
        assert {key: value for key, value in current.content.items() if key != 'materialIds'} == {
            key: value for key, value in original.items() if key != 'materialIds'}
        assert current.revision == work['revision'] + int(success)
        materials = (await db.scalars(select(WorkMaterial).where(WorkMaterial.owner_id == users['employee'].id))).all()
        assert len(materials) == (11 if success else 0)
        assert set(current.content.get('materialIds', [])) == {row.id for row in materials}
        if success:
            assert {json.dumps(row.source, sort_keys=True) for row in materials} == {json.dumps(value, sort_keys=True) for value in values}
            assert all(row.work_id == work['id'] for row in materials)
        actions = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == sent['messageId']))).all()
        assert len(actions) == int(success)
        live = await db.get(Job, job.id)
        if variant == 'scope-conflict':
            assert live.state in ('failed', 'awaiting_retry')
            assert '操作核对未返回完整有效结果' in live.error
            assert any('invalidFields' in text and 'allowed=true' in text and 'materials' in text for text in model.repairs)
            assert model.checks == 4 and model.calls == 2 and model.plans == 1
            visible = json.dumps(public, ensure_ascii=False)
            assert '操作核对未返回完整有效结果' not in visible and '内部核对未完成' not in visible
            assert public['job']['taskOutcome']['nextAction'] == 'retry'
            assert '稍后重试' in public['job']['error']
        else:
            assert model.checks == 1 and model.plans == 1
        if success:
            assert live.state == 'succeeded' and model.calls == 2
    refreshed = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert refreshed['job']['error'] == public['job']['error']
    if success:
        assert refreshed['job']['taskOutcome']['state'] == 'completed'


def test_controlled_error_projection_does_not_filter_technical_prose_or_other_failures():
    raw = '操作核对未返回完整有效结果，本次操作尚未执行'
    node = {'kind': 'authorization', 'errorCode': 'invalid_response', 'error': raw, 'scope': 'now'}
    job = SimpleNamespace(error=raw, result={'nodeExecution': {'scope': 'now', 'nodes': [node]}})
    assert job_error(job) == node_error(node) and '稍后重试' in job_error(job)
    assert node_error({**node, 'kind': 'model'}) == raw
    assert node_error({**node, 'errorCode': 'permission', 'error': '你没有权限访问这条工作'}) == '你没有权限访问这条工作'
    assert node_error({**node, 'errorCode': 'uncertain', 'error': '上次操作结果未知，请核对业务记录后再处理'}) == '上次操作结果未知，请核对业务记录后再处理'
    job.result['nodeExecution']['scope'] = 'new-input'
    assert job_error(job) == raw
    assert prose(raw, job, '解释授权核对错误日志') == raw


@pytest.mark.parametrize('index', [1, 3])
def test_complete_canonical_gap_response_defers_target_proof_to_destination(index):
    raw = copy.deepcopy(GAP_RESPONSES[index])
    payload = request()
    payload.update(messageId=raw['quoteMessageId'], currentUserText=raw['quote'], conversationTask={})
    normalized = normalize_contract(raw, payload)
    assert normalized == raw
    selected = resolve(WorkIntentVerdict.model_validate(normalized).materialSelection, payload)
    assert selected['destination'] == 'unselected' and not selected['destinationProof']
    assert len(selected['sources']) == 11


@pytest.mark.parametrize('updates,expected', [
    ({'allowed': True}, True),
    ({'failureKind': 'missing_info', 'denialScope': 'target'}, True),
    ({'failureKind': 'invalid_arguments', 'denialScope': 'fields'}, True),
    ({'failureKind': 'invalid_arguments', 'denialScope': 'other', 'requiredFields': ['body']}, True),
    ({'failureKind': 'invalid_arguments', 'denialScope': 'other'}, False),
    ({'failureKind': 'invalid_arguments', 'denialScope': 'source', 'requiredFields': ['body']}, False),
    ({'failureKind': 'invalid_arguments', 'denialScope': 'authorization'}, False),
    ({'failureKind': 'missing_info', 'denialScope': 'source'}, False),
    ({'failureKind': 'missing_info', 'denialScope': 'authorization'}, False),
    ({'failureKind': 'permission_denied', 'denialScope': 'fields'}, False),
    ({'failureKind': 'conflict', 'denialScope': 'fields'}, False),
    ({'failureKind': 'not_requested', 'denialScope': 'fields'}, False),
    ({'allowed': True, 'notRequested': True}, False),
])
def test_pending_destination_only_defers_candidate_field_coverage(updates, expected):
    verdict = WorkIntentVerdict.model_validate({'allowed': False, 'quote': TEXT, 'reason': '', **updates})
    assert destination_gap_precedes_fields(verdict, {'destination': 'unselected'}) is expected
    assert not destination_gap_precedes_fields(verdict, {'destination': 'existing'})
    assert not destination_gap_precedes_fields(verdict, None)


def test_schema_repair_feedback_is_bounded_and_contains_no_input_values():
    private = '不得回显的私有内容' * 200
    with pytest.raises(ValueError) as caught:
        WorkIntentVerdict.model_validate({'allowed': True, 'quote': private,
            'reason': '', 'quoteRange': {'start': private}, private: private})
    feedback = schema_feedback(caught.value)
    assert 'quoteRange: extra_forbidden' in feedback
    assert '<field>: extra_forbidden' in feedback
    assert '不得回显' not in feedback and len(feedback) < 700


def gap_model(sent, work, values, text, wire_for, *, source_message=None):
    class GapModel(BoundedChatModel):
        calls: int = 0
        checks: int = 0
        plans: int = 0
        repairs: list[str] = []
        async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
            payload = next((json.loads(m.content) for m in input if isinstance(m.content, str)
                and m.content.startswith('{') and ('"proposedOperation"' in m.content or '"work_change_plan"' in m.content)), {}) if isinstance(input, list) else {}
            if payload.get('task') == 'work_change_plan':
                self.plans += 1
                fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
                fields['materials'] = {'mode': 'set', 'value': None,
                    'quotes': [{'messageId': source_message or sent['messageId'], 'text': text}]}
                return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(fields))))
            if payload.get('proposedOperation'):
                self.checks += 1
                self.repairs.extend(m.content for m in input if isinstance(m.content, str) and m.content.startswith('本次核对输出须同时满足：'))
                result = AIMessage(content=json.dumps(planned_material_wire(wire_for(payload, self.checks)), ensure_ascii=False))
                # Real BoundedChatModel validates before returning; check()
                # parses again. Both passes must be side-effect free.
                if self._response_validator:
                    self._response_validator(result)
                return result
            return await super().ainvoke(input, config, stop=stop, **kwargs)
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            steps = [('load_tools', {'groups': ['work']}), ('get_work_item', {'work_id': work['id']}),
                ('execute_business_action', {'step': 1, 'action': 'update_work', 'target_id': work['id'],
                    'expected_revision': work['revision'], 'changes': {'materials': values}})]
            if self.calls > len(steps):
                assert self.calls == 4
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content='这次没有添加材料。'))])
            name, args = steps[self.calls - 1]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                'id': f'gap-{self.calls}', 'name': name, 'args': args}]))])
    return GapModel(model='controlled-gap', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0)


def with_scope_model(monkeypatch):
    original = handlers.RunContext
    def create_context(*args, **kwargs):
        result = original(*args, **kwargs)
        result.work_change_model = kwargs['intent_model']
        return result
    monkeypatch.setattr(handlers, 'RunContext', create_context)


def gap_wire(index, sent, work):
    raw = GAP_RESPONSES[index]
    return json.loads(json.dumps(raw, ensure_ascii=False).replace(
        raw['quoteMessageId'], sent['messageId']).replace(
        GAP_RESPONSES[1]['materialSelection']['targetId'], work['id']))


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', [1, 3, 'changing-errors'])
async def test_actual_gap_wires_ask_once_then_answer_saves_all_without_main_rewrite(setup, monkeypatch, variant):
    text = GAP_RESPONSES[1]['quote']
    job, sent, work, values, original = await runtime(setup, text=text, reference=False)
    settings, sessions, users, clients = setup
    with_scope_model(monkeypatch)
    def wire_for(payload, attempt):
        assert not payload['conversationTask'].get('workReference')
        if variant == 'changing-errors':
            if attempt == 1:
                raw = gap_wire(1, sent, work)
                raw['materialSelection'].pop('targetId')
                return raw
            return gap_wire({2: 0, 3: 2, 4: 3}[attempt], sent, work)
        return gap_wire(variant, sent, work)
    model = gap_model(sent, work, values, text, wire_for)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await handlers.process_job(job, sessions, settings, saver, model=model)
    public = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(public['interactions']) == 1, public
    assert model.calls == 3 and model.plans == 1
    assert model.checks == (4 if variant == 'changing-errors' else 1)
    if variant == 'changing-errors':
        assert len(model.repairs) == 3
        assert '没有可用的工作引用' in model.repairs[0]
        assert 'workChangeFields: extra_forbidden' in model.repairs[1]
        assert '没有可用的工作引用' in model.repairs[1]
        assert 'quoteRange: extra_forbidden' in model.repairs[2]
        assert 'workChangeFields: extra_forbidden' in model.repairs[2]
        assert '没有可用的工作引用' in model.repairs[2]
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert not live.result.get('workChangeRequirements')
        selected = live.result['materialCollections'][0]
        assert selected['destination'] == 'unselected' and not selected['targetId']
        assert {json.dumps(v, sort_keys=True) for v in selected['sources']} == {json.dumps(v, sort_keys=True) for v in values}
        assert (await db.get(WorkItem, work['id'])).content == original
        assert not await db.scalar(select(WorkMaterial.id).where(WorkMaterial.owner_id == users['employee'].id))
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))
    if variant != 3:
        return
    # Continue the actual persisted question, then reload the message and work.
    interaction = public['interactions'][0]
    question = interaction['questions'][0]
    matching_options = [item for item in question['options'] if item['label'] == work['title']]
    assert len(matching_options) == 1, question
    option = matching_options[0]
    answered = await clients['employee'].post('/api/v1/interactions/' + interaction['id'] + '/answer',
        json={'expectedRevision': interaction['revision'], 'answers': [
            {'questionId': question['id'], 'optionIds': [option['id']]}]}, headers=keyed())
    assert answered.status_code == 200, answered.text
    resumed = await claim(sessions, users['employee'].id)
    async with sessions() as db:
        message = await db.get(Message, resumed.target_id)
        resumed_sent = {'messageId': message.id}
    def selected_wire(payload, attempt):
        result = gap_wire(1, sent, work)
        result.update(resumeTask=True, receiptOnly=True)
        result['materialSelection'] = {'mode': 'previous', 'previousId': selected['id'],
            'destination': 'existing', 'targetId': work['id'], 'destinationEvidence': {'source': 'interaction'}}
        result['taskContext']['relation'] = 'continue'
        return result
    continuation = gap_model(resumed_sent, work, values, text, selected_wire, source_message=sent['messageId'])
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await handlers.process_job(resumed, sessions, settings, saver, model=continuation)
    refreshed = (await clients['employee'].get('/api/v1/messages/' + resumed_sent['messageId'])).json()
    assert refreshed['job']['state'] == 'succeeded', refreshed
    assert refreshed['job']['taskOutcome']['state'] == 'completed'
    assert continuation.calls == 3 and continuation.checks == 1 and continuation.plans == 1
    async with sessions() as db:
        current = await db.get(WorkItem, work['id'])
        assert current.revision == work['revision'] + 1
        assert {k: v for k, v in current.content.items() if k != 'materialIds'} == {k: v for k, v in original.items() if k != 'materialIds'}
        materials = (await db.scalars(select(WorkMaterial).where(WorkMaterial.work_id == work['id']))).all()
        assert len(materials) == 11
        assert {json.dumps(v.source, sort_keys=True) for v in materials} == {json.dumps(v, sort_keys=True) for v in values}
        assert len((await db.scalars(select(BusinessAction).where(BusinessAction.message_id == resumed_sent['messageId']))).all()) == 1


@pytest.mark.asyncio
async def test_real_high_target_and_scope_gap_persists_before_write_then_http_answer_saves(setup, monkeypatch):
    text = CLARIFICATION_RESPONSE['quote']
    job, sent, work, values, original = await runtime(setup, text=text, reference=False)
    settings, sessions, users, clients = setup
    with_scope_model(monkeypatch)
    raw = CLARIFICATION_RESPONSE
    wire = json.dumps(raw, ensure_ascii=False).replace(raw['materialSelection']['messageId'], sent['messageId']).replace(
        raw['missingInputs'][0]['candidateIds'][0], work['id'])
    model = gap_model(sent, work, values, text, lambda payload, attempt: json.loads(wire))
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await handlers.process_job(job, sessions, settings, saver, model=model)
    public = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert model.calls == 3 and model.checks == 1 and model.plans == 1
    assert public['job']['state'] == 'awaiting_input' and len(public['interactions']) == 1
    panel = public['interactions'][0]
    target, scope = panel['questions']
    assert target['prompt'] == raw['missingInputs'][0]['question']
    assert scope['prompt'] == raw['missingInputs'][1]['question']
    assert scope['type'] == 'text' and scope['options'] == []
    assert [option['label'] for option in target['options']] == [work['title']]
    assert raw['reason'] not in json.dumps(public, ensure_ascii=False)
    async with sessions() as db:
        live = await db.get(Job, job.id)
        assert live.result['toolOutcomes'][0]['recovery']['missingInputs'] == json.loads(wire)['missingInputs']
        assert not live.result.get('materialCollections')
        assert any(node['kind'] == 'tool' and node['state'] == 'awaiting_input'
                   for node in live.result['nodeExecution']['nodes'])
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))
        assert not await db.scalar(select(WorkMaterial.id).where(WorkMaterial.owner_id == users['employee'].id))
        assert (await db.get(WorkItem, work['id'])).content == original
    answered = await clients['employee'].post('/api/v1/interactions/' + panel['id'] + '/answer', json={
        'expectedRevision': panel['revision'], 'answers': [
            {'questionId': target['id'], 'optionIds': [target['options'][0]['id']]},
            {'questionId': scope['id'], 'text': '保存当前会话生成的全部文件，原工作内容保持不变。'}]}, headers=keyed())
    assert answered.status_code == 200, answered.text
    resumed = await claim(sessions, users['employee'].id)
    async with sessions() as db:
        reply = await db.get(Message, resumed.target_id)
        resumed_sent, reply_text = {'messageId': reply.id}, reply.text
    def approved(payload, attempt):
        result = gap_wire(1, resumed_sent, work)
        result.update(quote=reply_text, resumeTask=True, receiptOnly=True)
        result['requestedChanges'] = [{'quote': reply_text, 'field': 'materials', 'kind': 'material'}]
        result['materialSelection'] = {'mode': 'all', 'quote': reply_text, 'messageId': reply.id,
            'destination': 'existing', 'targetId': work['id'], 'destinationEvidence': {'source': 'interaction'}}
        result['taskContext']['relation'] = 'continue'
        return result
    continuation = gap_model(resumed_sent, work, values, reply_text, approved)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await handlers.process_job(resumed, sessions, settings, saver, model=continuation)
    final = (await clients['employee'].get('/api/v1/messages/' + resumed_sent['messageId'])).json()
    assert final['job']['state'] == 'succeeded' and not final['interactions'], final
    assert continuation.calls == 3 and continuation.checks == 1 and continuation.plans == 1
    async with sessions() as db:
        current = await db.get(WorkItem, work['id'])
        assert current.revision == work['revision'] + 1
        assert {k: v for k, v in current.content.items() if k != 'materialIds'} == {
            k: v for k, v in original.items() if k != 'materialIds'}
        rows = (await db.scalars(select(WorkMaterial).where(WorkMaterial.work_id == work['id']))).all()
        assert {json.dumps(row.source, sort_keys=True) for row in rows} == {json.dumps(v, sort_keys=True) for v in values}
        assert len((await db.scalars(select(BusinessAction).where(BusinessAction.message_id == reply.id))).all()) == 1
