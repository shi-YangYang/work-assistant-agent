"""Selected collections survive repair and are completed by actual bindings."""
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.agent.actions.material_selection import MaterialSelection, issue, resolve
from app.agent.actions.operations import execute
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.messages.models import Message
from app.modules.work.models import WorkMaterial
from app.tasks.feedback.material_requirements import collections, remember, settle, uncovered
from app.tasks.feedback.outcomes import derive
from app.tasks.models import Job
from _support.agent.execution_permissions import mode_runtime

pytestmark = pytest.mark.asyncio


def sources(count=11):
    return [{'deliverableId': f'd-{i}', 'revision': 1, 'fileId': f'f-{i}'} for i in range(count)]


def request(values, *, target=''):
    return {'messageId': 'message', 'currentUserText': '新建工作，把之前的全部文件保存进去',
        'conversationTask': {}, 'privateDeliverables': {'collectionComplete': True,
            'items': [{'files': [{'materialSource': source}]} for source in values]},
        'proposedOperation': {'action': 'update_work' if target else 'create_work', 'targetId': target,
                             'changes': {'materials': values[:2]}}}


def destination_quote(payload):
    return {'source': 'user', 'messageId': payload['messageId'], 'quote': payload['currentUserText']}


async def test_all_is_independent_of_old_failed_proposal_and_subset_remains_exact():
    from app.agent.actions.intent import WorkIntentVerdict
    values = sources()
    payload = request(values)
    payload['conversationTask']['previousTask'] = {'items': [{'attemptedOperation': {
        'action': 'create_work', 'changes': {'materials': values[:2]}}}]}
    selection = resolve(MaterialSelection(mode='all', quote=payload['currentUserText'], destination='new',
        destinationEvidence=destination_quote(payload)), payload)
    failure = issue(selection, payload['proposedOperation'], [])
    assert failure['missingMaterials'] == values[2:]
    subset = resolve(MaterialSelection(mode='selected', quote=payload['currentUserText'],
        references=values[:2], destination='new', destinationEvidence=destination_quote(payload)), payload)
    assert issue(subset, payload['proposedOperation'], []) is None
    with pytest.raises(ValueError, match='none'):
        resolve(MaterialSelection(), payload)
    missing = WorkIntentVerdict.model_validate({'allowed': True, 'quote': payload['currentUserText'], 'reason': ''})
    with pytest.raises(ValueError, match='none'):
        resolve(missing.materialSelection, payload)
    assert resolve(missing.materialSelection, {**payload, 'proposedOperation': {'changes': {'status': 'done'}}}) is None
    directive = {**payload, 'currentUserText': '这些也保存', 'conversationTask': {
        'activeDirectives': [{'messageId': 'directive', 'quote': '后续文件保存到项目资料', 'userText': '后续文件保存到项目资料', 'targetId': 'work'}]}}
    assert resolve(MaterialSelection(mode='selected', quote='后续文件保存到项目资料', messageId='directive',
        references=values[:2], destination='existing', targetId='work',
        destinationEvidence={'source': 'directive', 'messageId': 'directive'}), directive)['sources'] == values[:2]
    payload['privateDeliverables']['collectionComplete'] = False
    with pytest.raises(ValueError, match='完整'):
        resolve(MaterialSelection(mode='all', quote=payload['currentUserText']), payload)


async def test_missing_target_keeps_collection_and_answer_reuses_it():
    values = sources()
    payload = request(values)
    selection = resolve(MaterialSelection(mode='all', quote=payload['currentUserText']), payload)
    assert issue(selection, payload['proposedOperation'], [])['field'] == 'target'
    job = SimpleNamespace(target_id='message', result={})
    selection = remember(job, selection, item_id='failed-create')
    resumed = {**payload, 'messageId': 'reply', 'currentUserText': '放到资料整理',
        'verifiedReads': {'ownWorkRead': [{'id': 'chosen', 'title': '资料整理'}]},
        'conversationTask': {'previousTask': {'materialCollections': collections(job)}}}
    resolved = resolve(MaterialSelection(mode='previous', previousId=selection['id'],
        destination='existing', targetId='chosen', destinationEvidence=destination_quote(resumed)), resumed, resume=True)
    assert resolved['sources'] == values
    assert resolved['id'] == selection['id']
    assert issue(resolved, {'action': 'update_work', 'targetId': 'chosen', 'changes': {'materials': values}}, []) is None


@pytest.mark.parametrize('mode', ['all', 'previous'])
@pytest.mark.parametrize('evidence_source', ['none', 'user', 'work_reference', 'interaction', 'directive'])
async def test_repeated_unanswered_words_do_not_select_a_destination(mode, evidence_source):
    values = sources()
    payload = request(values)
    payload['currentUserText'] = '之前的都添加到我的工作里面'
    selected = resolve(MaterialSelection(mode='all', quote=payload['currentUserText']), payload)
    job = SimpleNamespace(result={})
    selected = remember(job, selected, item_id='old-proposal')
    repeated = {**payload, 'messageId': 'repeat', 'materialCollections': [selected],
        'conversationTask': {'interactionAnswers': [{'text': payload['currentUserText'], 'selected': []}],
            'previousTask': {'state': 'needs_input', 'userSources': [
            {'messageId': 'message', 'userText': payload['currentUserText']}],
            'items': [{'id': 'old-proposal', 'state': 'proposed', 'action': 'create_work', 'targetId': ''}]}}}
    result = resolve(MaterialSelection(mode=mode, quote=payload['currentUserText'], previousId=selected['id'],
        destination='new', destinationEvidence={**destination_quote(repeated), 'source': evidence_source}), repeated, resume=True)
    assert result['destination'] == 'unselected'
    assert result['sources'] == values
    assert issue(result, payload['proposedOperation'], [])['field'] == 'target'


async def test_legacy_unresolved_destination_requires_new_evidence_but_explicit_selection_can_continue():
    values = sources()
    payload = request(values)
    payload['currentUserText'] = '之前的都添加到我的工作里面'
    payload['conversationTask']['previousTask'] = {'state': 'needs_input', 'userSources': [
        {'messageId': 'old', 'userText': payload['currentUserText']}], 'items': [
        {'id': 'old-item', 'state': 'proposed', 'action': 'create_work', 'targetId': '', 'label': '新建资料工作'}]}
    payload['verifiedReads'] = {'ownWorkRead': [{'id': 'only-work', 'title': '资料工作'}]}
    for target, identifier in [('new', ''), ('existing', 'only-work')]:
        result = resolve(MaterialSelection(mode='all', quote=payload['currentUserText'], destination=target,
            targetId=identifier, destinationEvidence=destination_quote(payload)), payload, resume=True)
        assert result['destination'] == 'unselected'
    # The older opaque task has no verified collection to supply an omitted
    # object type. Preserve this compatibility boundary explicitly.
    elliptical = {**payload, 'messageId': 'answer', 'currentUserText': '另建一项保存这些文件'}
    assert resolve(MaterialSelection(mode='all', quote=payload['currentUserText'], messageId='old',
        destination='new', destinationEvidence=destination_quote(elliptical)), elliptical, resume=True)['destination'] == 'unselected'
    for text, target, identifier in [('另建一项工作保存这些文件', 'new', ''), ('就放到资料工作', 'existing', 'only-work')]:
        reply = {**payload, 'messageId': 'answer', 'currentUserText': text}
        value = MaterialSelection(mode='all', quote=payload['currentUserText'], messageId='old',
            destination=target, targetId=identifier, destinationEvidence=destination_quote(reply))
        result = resolve(value, reply, resume=True)
        assert result['destination'] == target and result['targetId'] == identifier
        assert result['sources'] == values
        forged = value.model_copy(update={'destinationEvidence': value.destinationEvidence.model_copy(
            update={'messageId': 'old', 'quote': payload['currentUserText']})})
        assert resolve(forged, reply, resume=True)['destination'] == 'unselected'


async def test_only_actual_target_reference_answer_or_bound_directive_is_evidence():
    values = sources()
    payload = request(values)
    chosen = {'mode': 'all', 'quote': payload['currentUserText'], 'destination': 'existing', 'targetId': 'chosen'}
    for task, evidence in [
        ({'workReference': {'id': 'chosen'}}, {'source': 'work_reference'}),
        ({'interactionAnswers': [{'text': '', 'selected': [{'objectType': 'work', 'objectId': 'chosen'}]}]}, {'source': 'interaction'}),
        ({'activeDirectives': [{'messageId': 'instruction', 'targetId': 'chosen', 'quote': '后续文件保存到所选工作'}]}, {'source': 'directive', 'messageId': 'instruction'}),
    ]:
        selected = resolve(MaterialSelection(**chosen, destinationEvidence=evidence), {**payload, 'conversationTask': task})
        assert selected['targetId'] == 'chosen'
        wrong = resolve(MaterialSelection(**{**chosen, 'targetId': 'other'}, destinationEvidence=evidence), {**payload, 'conversationTask': task})
        assert wrong['destination'] == 'unselected'
    unavailable = {**payload, 'conversationTask': {'workReference': {'id': 'chosen', 'unavailable': True}}}
    assert resolve(MaterialSelection(**chosen, destinationEvidence={'source': 'work_reference'}), unavailable)['destination'] == 'unselected'
    reply = {**payload, 'conversationTask': {'interactionAnswers': [{'text': '', 'selected': [{'id': 'new', 'label': '新建一条工作'}]}]}}
    value = MaterialSelection(mode='all', quote=payload['currentUserText'], destination='new',
        destinationEvidence={'source': 'interaction', 'quote': '新建一条工作'})
    assert resolve(value, reply)['destination'] == 'new'
    reply['conversationTask']['interactionAnswers'][0]['selected'] = []
    assert resolve(value, reply)['destination'] == 'unselected'


async def test_receipts_cover_only_same_item_target_and_version_and_large_batch_continues():
    values = sources(21)
    payload = request(values)
    selection = resolve(MaterialSelection(mode='all', quote=payload['currentUserText'], destination='new',
        destinationEvidence=destination_quote(payload)), payload)
    job = SimpleNamespace(target_id='message', state='succeeded', result={})
    first = remember(job, selection, item_id='first-independent-work')
    second = remember(job, selection, item_id='second-independent-work')
    assert first['id'] != second['id']
    card = {'id': 'receipt', 'action': 'create_work', 'state': 'succeeded', 'objectId': 'created',
            'taskItemId': 'first-independent-work', 'materialSources': values[:20]}
    assert issue(first, {'action': 'create_work', 'changes': {'materials': values[:20]}}, []) is None
    settle(job, card)
    first = next(item for item in collections(job) if item['id'] == first['id'])
    assert first['targetId'] == 'created'
    assert uncovered(first, [card]) == values[20:]
    assert uncovered(second, [card]) == values
    outcome = derive(job, [card], interpretation={'state': 'completed', 'remaining': []})
    assert outcome['state'] == 'partial' and outcome['remaining']
    payload['materialCollections'] = [first]
    previous = resolve(MaterialSelection(mode='previous', previousId=first['id'],
        destination='existing', targetId='created'), payload)
    assert issue(previous, {'action': 'update_work', 'targetId': 'created',
        'changes': {'materials': values[20:]}}, [card]) is None
    with pytest.raises(ValueError, match='同一工作'):
        resolve(MaterialSelection(mode='previous', previousId=first['id'],
            destination='new'), payload)
    wrong_revision = {**card, 'materialSources': [{**source, 'revision': 2} for source in values[:20]]}
    assert uncovered(first, [wrong_revision]) == values
    assert uncovered(first, [{**card, 'objectId': 'another'}]) == values
    legacy = {key: value for key, value in first.items() if key != 'destinationProof'}
    payload['materialCollections'], payload['completedOrPendingSteps'] = [legacy], [card]
    restored = resolve(MaterialSelection(mode='previous', previousId=first['id']), payload)
    assert restored['targetId'] == 'created'
    assert restored['destinationProof'] == {'source': 'receipt', 'receiptId': 'receipt'}
    payload['completedOrPendingSteps'] = [{**card, 'taskItemId': 'other-item'}]
    unresolved = resolve(MaterialSelection(mode='previous', previousId=first['id'],
        destination='existing', targetId='created'), payload)
    assert unresolved['destination'] == 'unselected'


async def seed_files(context, count=11):
    values = []
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        message = await db.get(Message, job.target_id)
        directory = context.settings.media_dir / 'generated'
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            content = f'material {i}'.encode()
            checksum = hashlib.sha256(content).hexdigest()
            (directory / checksum).write_bytes(content)
            item = Deliverable(company_id=job.company_id, owner_id=job.owner_id,
                conversation_id=message.conversation_id, title=f'文件 {i}', access=message.access)
            db.add(item)
            await db.flush()
            file_id = str(uuid4())
            db.add(DeliverableRevision(company_id=job.company_id, owner_id=job.owner_id,
                deliverable_id=item.id, revision=1, message_id=message.id, step=i + 1,
                title=item.title, body='真实测试文件', digest=checksum,
                files=[{'id': file_id, 'name': 'same.txt', 'mimeType': 'text/plain',
                        'size': len(content), 'sha256': checksum, 'storageKey': checksum, 'sources': []}]))
            values.append({'deliverableId': item.id, 'revision': 1, 'fileId': file_id})
    return values


async def referenced_material_runtime(setup, text):
    from app.tasks.context import RunContext
    from app.tasks.runtime.queue import claim
    from _support.agent.business_actions import create
    from _support.agent.execution_permissions import set_mode
    from _support.http.company import keyed
    settings, sessions, users, clients = setup
    await set_mode(clients['employee'], 'full')
    work = await create(clients['employee'], '资料整理', summary='原来的工作内容必须保留')
    await create(clients['employee'], '资料整理', summary='同名工作不可被修改')
    response = await clients['employee'].post('/api/v1/messages', json={
        'newConversation': True, 'text': text, 'workReference': {'workId': work['id']}}, headers=keyed())
    assert response.status_code == 202, response.text
    sent = response.json()
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    return context, sent, work


async def test_worker_current_reference_saves_all_without_source_label_roundtrip(setup, monkeypatch):
    """HTTP/worker reproduction of E01 high's provenance-label mismatch."""
    from langchain_openai import ChatOpenAI
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    from app.tasks.processing import handlers
    text = '之前生成的这些文件都加到这条工作里，原来的工作内容保留。'
    context, sent, work = await referenced_material_runtime(setup, text)
    values = await seed_files(context)
    async with context.sessions() as db:
        original_body = (await db.get(WorkItem, work['id'])).content['body']
        job = await db.get(Job, context.job_id)
    original_context = handlers.RunContext
    def with_plan(*args, **kwargs):
        result = original_context(*args, **kwargs)
        result.work_change_model = kwargs['intent_model']
        return result
    monkeypatch.setattr(handlers, 'RunContext', with_plan)

    class ReferencedModel(ChatOpenAI):
        calls: int = 0
        plans: int = 0
        checks: int = 0
        async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
            try:
                payload = json.loads(input[-1].content) if isinstance(input, list) else {}
            except (ValueError, TypeError):
                payload = {}
            if payload.get('task') == 'work_change_plan':
                self.plans += 1
                fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
                fields['materials'] = {'mode': 'set', 'value': None,
                    'quotes': [{'messageId': sent['messageId'], 'text': text}]}
                return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(fields))))
            if payload.get('proposedOperation'):
                self.checks += 1
                reference = payload['conversationTask']['workReference']
                assert reference['id'] == work['id'] and not reference.get('unavailable')
                return AIMessage(content=json.dumps({'allowed': True, 'quote': text, 'reason': '',
                    'receiptOnly': True, 'invalidFields': [],
                    'materialSelection': {'mode': 'all', 'quote': text, 'destination': 'existing',
                        'targetId': work['id'], 'destinationEvidence': destination_quote(payload)}}))
            return await super().ainvoke(input, config, stop=stop, **kwargs)
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            steps = [('load_tools', {'groups': ['work']}), ('execute_business_action', {
                'step': 1, 'action': 'update_work', 'target_id': work['id'],
                'expected_revision': work['revision'], 'changes': {'materials': values}})]
            assert self.calls <= len(steps), 'A validated reference needs no additional read or clarification'
            name, args = steps[self.calls - 1]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                'id': f'reference-{self.calls}', 'name': name, 'args': args}]))])

    model = ReferencedModel(model='controlled-reference', api_key='test-no-network',
        base_url='http://127.0.0.1:1', max_retries=0)
    async with AsyncPostgresSaver.from_conn_string(context.settings.checkpoint_url) as saver:
        await handlers.process_job(job, context.sessions, context.settings, saver, model=model)
    response = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert response['job']['state'] == 'succeeded', response['job']
    assert not response['interactions']
    assert model.calls == 2 and model.plans == 1 and model.checks == 1
    async with context.sessions() as db:
        live = await db.get(Job, context.job_id)
        selected = collections(live)[0]
        assert selected['targetId'] == work['id']
        assert {json.dumps(value, sort_keys=True) for value in selected['sources']} == {json.dumps(value, sort_keys=True) for value in values}
        assert selected['destinationProof'] == {'source': 'work_reference', 'messageId': sent['messageId'], 'quote': text}
        current = await db.get(WorkItem, work['id'])
        assert current.content['body'] == original_body and current.revision == work['revision'] + 1
        materials = (await db.scalars(select(WorkMaterial).where(WorkMaterial.work_id == work['id']))).all()
        assert {json.dumps(row.source, sort_keys=True) for row in materials} == {json.dumps(value, sort_keys=True) for value in values}
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.owner_id == context.owner_id)) == 11
        actions = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == sent['messageId']))).all()
        assert len(actions) == 1 and actions[0].state == 'succeeded'
    refreshed = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert refreshed['job']['taskOutcome']['state'] == 'completed'
    assert not refreshed['interactions']


@pytest.mark.parametrize('rejection', ['not_requested', 'permission_denied', 'invalid_arguments', 'invalid_quote'])
async def test_current_reference_is_not_permission_or_field_authorization(setup, rejection):
    from app.agent.context.task_context import projection
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    text = '只看这条工作，不要添加文件' if rejection == 'not_requested' else '把这些文件加到这条工作里'
    context, sent, work = await referenced_material_runtime(setup, text)
    values = await seed_files(context, 1)
    # Direct execute tests perform the same reference projection as worker
    # startup, including its read-version registration before execution.
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        await projection(db, setup[2]['employee'], job, await db.get(Message, sent['messageId']), context)
    class Refusal:
        calls = 0
        async def ainvoke(self, messages):
            self.calls += 1
            payload = json.loads(messages[-1].content)
            return AIMessage(content=json.dumps({'allowed': rejection == 'invalid_quote',
                'notRequested': rejection == 'not_requested', 'failureKind': rejection if rejection != 'invalid_quote' else 'invalid_arguments',
                'quote': '不存在的授权原话' if rejection == 'invalid_quote' else text,
                'reason': '受控拒绝', 'denialScope': 'fields' if rejection == 'invalid_arguments' else 'authorization',
                'requiredFields': ['body'] if rejection == 'invalid_arguments' else [],
                'materialSelection': {'mode': 'all', 'quote': text, 'destination': 'existing',
                    'targetId': work['id'], 'destinationEvidence': destination_quote(payload)}}))
    context.intent_model = Refusal()
    result = await execute(context, step=1, action='update_work', target_id=work['id'],
        expected_revision=work['revision'], changes={'materials': values})
    assert result['state'] != 'clarification' and result['state'] != 'succeeded', result
    assert result.get('category', result['state']) == ('invalid_arguments' if rejection == 'invalid_quote' else rejection)
    assert context.intent_model.calls == 1
    async with context.sessions() as db:
        assert (await db.get(WorkItem, work['id'])).revision == work['revision']
        assert not await db.scalar(select(WorkMaterial.id).where(WorkMaterial.owner_id == context.owner_id))
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))


class AllJudge:
    def __init__(self, *, destination='new'):
        self.destination = destination
        self.inputs = []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        candidates = payload.get('failedItemCandidates', [])
        return AIMessage(content=json.dumps({
            'allowed': True, 'quote': payload['currentUserText'], 'reason': '',
            'taskItemId': candidates[0]['id'] if candidates else '',
            'receiptOnly': True,
            'materialSelection': {'mode': 'all', 'quote': payload['currentUserText'],
                                  'destination': self.destination, 'destinationEvidence': destination_quote(payload)},
        }))


async def test_real_create_cannot_save_two_as_complete_then_corrects_once_without_duplicate(setup):
    context, sent = await mode_runtime(setup, 'full', '新建一项工作，把之前的全部文件都保存进去')
    values = await seed_files(context)
    context.intent_model = AllJudge()
    result = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': values[:2]})
    assert result['state'] == 'failed', result
    assert len(result['recovery']['missingMaterials']) == 9
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkMaterial)) == 0
        job = await db.get(Job, context.job_id)
        assert len(collections(job)[0]['sources']) == 11
    saved = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': values})
    assert saved['state'] == 'succeeded', saved
    assert len(saved['materialSources']) == 11
    repeated = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': values})
    assert repeated['id'] == saved['id']
    async with context.sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state = 'succeeded'
        assert derive(job, [saved], interpretation={'state': 'completed', 'remaining': []})['state'] == 'completed'
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(
            WorkMaterial.work_id == saved['objectId'])) == 11


async def test_target_gap_is_saved_before_asking_and_cannot_invent_new_destination(setup):
    from app.agent.actions.interactions import ask, finish_waiting
    from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan
    from app.tasks.context import RunContext
    from app.tasks.runtime.queue import claim
    from _support.agent.business_actions import create, read_work
    from _support.http.company import keyed
    context, sent = await mode_runtime(setup, 'full', '之前的都添加到我的工作里面')
    values = await seed_files(context)
    context.intent_model = AllJudge(destination='unselected')
    result = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': values})
    assert result['state'] == 'waiting', result
    assert [entry['field'] for entry in result['recovery']['missingInputs']] == ['target']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert len(collections(job)[0]['sources']) == 11
        assert collections(job)[0]['targetId'] == ''
        assert not any(item.get('receiptId') for item in job.result['taskItems'])
        selected_id = collections(job)[0]['id']
    work = await create(setup[3]['employee'], '资料整理')
    await read_work(context, work['id'])
    asked = await ask(context, [{'id': 'work', 'prompt': '保存到哪项工作？', 'type': 'single',
        'options': [{'id': 'a', 'label': work['title'], 'objectType': 'work', 'objectId': work['id']}]}])
    assert await finish_waiting(context)
    answer = await setup[3]['employee'].post('/api/v1/interactions/' + asked['interactionId'] + '/answer',
        json={'expectedRevision': 1, 'answers': [{'questionId': 'work', 'optionIds': ['a']}]}, headers=keyed())
    assert answer.status_code == 200, answer.text
    live = await claim(context.sessions, context.owner_id)
    context = RunContext(live.owner_id, live.company_id, live.id, live.fence, context.sessions, context.settings, source_revision=0)
    quote = '之前的都添加到我的工作里面'
    class ContinuedJudge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert payload['conversationTask']['interactionAnswers'][0]['selected'][0]['objectId'] == work['id']
            assert len(payload['materialCollections'][0]['sources']) == 11
            assert 'materialCollections' not in payload['conversationTask']['previousTask']
            return AIMessage(content=json.dumps({'allowed': True, 'quote': quote,
                'quoteMessageId': sent['messageId'], 'resumeTask': True, 'reason': '',
                'invalidFields': [],
                'materialSelection': {'mode': 'previous', 'previousId': selected_id,
                                      'destination': 'existing', 'targetId': work['id'],
                                      'destinationEvidence': {'source': 'interaction'}}}))
    class ContinuedPlan:
        async def ainvoke(self, messages):
            output = {field: {'mode': 'preserve', 'quotes': [], 'value': None} for field in FIELDS}
            output['materials'] = {'mode': 'set', 'value': None,
                'quotes': [{'messageId': sent['messageId'], 'text': quote}]}
            return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(output))))
    context.intent_model, context.work_change_model = ContinuedJudge(), ContinuedPlan()
    await read_work(context, work['id'])
    saved = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1,
        changes={'materials': values})
    assert saved['state'] == 'succeeded', saved
    assert len(saved['materialSources']) == 11
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert collections(job)[0]['id'] == selected_id
        assert collections(job)[0]['targetId'] == work['id']
        job.state = 'succeeded'
        assert derive(job, [saved], interpretation={'state': 'completed', 'remaining': []})['state'] == 'completed'
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.work_id == work['id'])) == 11


@pytest.mark.parametrize('legacy', [False, True])
async def test_http_repeated_request_cannot_choose_new_but_natural_target_answer_finishes(setup, legacy):
    from app.agent.actions.interactions import ask, finish_waiting
    from app.modules.conversations.task.task_state import store_for
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    from app.tasks.context import RunContext
    from app.tasks.runtime.queue import claim
    from _support.http.company import keyed
    text = '之前的都添加到我的工作里面'
    context, original = await mode_runtime(setup, 'full', text)
    values = await seed_files(context)
    context.intent_model = AllJudge(destination='unselected')
    before = await execute(context, step=1, action='create_work', changes={'title': '材料归档', 'materials': values})
    assert before['state'] == 'waiting'
    await ask(context, [{'id': 'destination', 'prompt': '保存到哪项工作，还是新建一项？', 'type': 'text'}])
    assert await finish_waiting(context)
    if legacy:
        # Production predates materialCollections. Preserve the real user source,
        # unsuccessful item and needs_input state, rather than a ready-made grant.
        async with context.sessions.begin() as db:
            message = await db.get(Message, original['messageId'])
            row = await store_for(db, setup[2]['employee'], message.conversation_id)
            row.payload = {**row.payload, 'task': {key: value for key, value in row.payload['task'].items()
                                                 if key != 'materialCollections'}}

    async def send_followup(text):
        response = await setup[3]['employee'].post('/api/v1/messages', json={
            'conversationId': original['conversationId'], 'text': text}, headers=keyed())
        assert response.status_code == 202, response.text
        live = await claim(context.sessions, context.owner_id)
        return RunContext(live.owner_id, live.company_id, live.id, live.fence,
            context.sessions, context.settings, source_revision=0)

    context = await send_followup(text)
    class RepeatingJudge(AllJudge):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            return AIMessage(content=json.dumps({**json.loads(response.content), 'resumeTask': True}))
    context.intent_model = RepeatingJudge(destination='new')
    repeated = await execute(context, step=1, action='create_work', changes={'title': '材料归档', 'materials': values})
    assert repeated['state'] == 'waiting', repeated
    assert [entry['field'] for entry in repeated['recovery']['missingInputs']] == ['target']
    async with context.sessions() as db:
        live = await db.get(Job, context.job_id)
        selected = collections(live)[0]
        assert selected['destination'] == 'unselected'
        assert sorted(selected['sources'], key=lambda source: source['fileId']) == sorted(values, key=lambda source: source['fileId'])
        for model in (WorkItem, WorkMaterial, BusinessAction):
            assert await db.scalar(select(func.count()).select_from(model).where(model.owner_id == context.owner_id)) == 0
    await ask(context, [{'id': 'destination', 'prompt': '保存到哪项工作，还是新建一项？', 'type': 'text'}])
    assert await finish_waiting(context)
    context = await send_followup('另建一条保存就好')
    class AnswerJudge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            previous = payload.get('materialCollections') or payload['conversationTask']['previousTask']['materialCollections']
            assert len(previous[0]['sources']) == 11
            return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'],
                'reason': '', 'resumeTask': True, 'receiptOnly': True,
                'materialSelection': {'mode': 'previous', 'previousId': previous[0]['id'], 'destination': 'new',
                    'destinationEvidence': destination_quote(payload)}}))
    context.intent_model = AnswerJudge()
    saved = await execute(context, step=1, action='create_work', changes={'title': '材料归档', 'materials': values})
    assert saved['state'] == 'succeeded', saved
    assert saved['materialSources'] == values
    async with context.sessions.begin() as db:
        live = await db.get(Job, context.job_id)
        live.state = 'succeeded'
        assert derive(live, [saved], interpretation={'state': 'completed', 'remaining': []})['state'] == 'completed'
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == context.owner_id)) == 1
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.work_id == saved['objectId'])) == 11


async def test_wrong_source_identity_can_be_repaired_without_reserving_a_write_step(setup):
    from app.modules.operations.models import BusinessAction
    context, sent = await mode_runtime(setup, 'full', '新建工作并保存之前的全部文件')
    values = await seed_files(context, 2)
    context.intent_model = AllJudge()
    wrong = [{**values[0], 'deliverableId': sent['messageId']}, values[1]]
    rejected = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': wrong})
    assert rejected['state'] == 'failed', rejected
    assert rejected['recovery']['unexpectedMaterials'] == wrong[:1]
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(
            BusinessAction.message_id == sent['messageId'])) == 0
    saved = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': values})
    assert saved['state'] == 'succeeded', saved
    assert saved['materialSources'] == values
    again = await execute(context, step=1, action='create_work',
        changes={'title': '资料整理', 'materials': values})
    assert again['id'] == saved['id']


async def pending_material_write(setup, mode, channel, *, confirmation=True):
    from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan
    from app.modules.attachments.models import Attachment
    from app.modules.work.records.record_commands import mutate_record
    from _support.agent.business_actions import create, read_work
    text = '把这份材料保存到资料整理' + ('，先让我确认' if confirmation else '')
    context, sent = await mode_runtime(setup, mode, text)
    work = await create(setup[3]['employee'], '资料整理')
    seeded = await seed_files(context, 2 if channel in ('materialIds', 'updateMaterialIds') else 1)
    values = seeded[:1]
    changes, extra = {'materials': values}, {}
    field = 'materials'
    if channel == 'update':
        changes, field = {'update': {'action': 'create', 'text': '保存材料', 'materials': values}}, 'update'
    elif channel in ('materialIds', 'updateMaterialIds'):
        async with context.sessions.begin() as db:
            saved = await mutate_record(db, setup[2]['employee'], work['id'],
                {'materials': seeded}, expected=1, settings=context.settings,
                conversation_id=sent['conversationId'])
            work, ids = saved['work'], saved['materialIds'][:1]
        if channel == 'updateMaterialIds':
            changes, field = {'update': {'action': 'create', 'text': '引用材料', 'materialIds': ids}}, 'update'
        else:
            changes = {'materialIds': ids}
    elif channel == 'shared':
        content = b'original attached text'
        async with context.sessions.begin() as db:
            attachment = Attachment(company_id=context.company_id, owner_id=context.owner_id,
                message_id=sent['messageId'], kind='document', mime='text/plain', name='original.txt',
                size=len(content), sha256=hashlib.sha256(content).hexdigest())
            db.add(attachment)
            await db.flush()
            (context.settings.media_dir / attachment.id).write_bytes(content)
            values = [{'attachmentId': attachment.id}]
        changes, field, extra = {}, None, {'shared_attachment_ids': [values[0]['attachmentId']]}
    class PendingJudge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            quote = payload['currentUserText']
            return AIMessage(content=json.dumps({'allowed': True, 'quote': quote, 'reason': '',
                'receiptOnly': True, 'requireConfirmation': confirmation,
                'invalidFields': [],
                'materialSelection': {'mode': 'selected', 'quote': quote, 'references': values,
                                      'destination': 'existing', 'targetId': work['id'],
                                      'destinationEvidence': destination_quote(payload)}}))
    class PendingPlan:
        async def ainvoke(self, messages):
            output = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
            if field:
                output[field] = {'mode': 'set', 'value': None,
                    'quotes': [{'messageId': sent['messageId'], 'text': text}]}
            return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(output))))
    context.intent_model, context.work_change_model = PendingJudge(), PendingPlan()
    await read_work(context, work['id'])
    card = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=work['revision'],
        changes=changes, **extra)
    assert card['state'] == ('pending' if confirmation or mode == 'ask' else 'succeeded'), card
    return context, work, values, card


@pytest.mark.parametrize('mode', ['ask', 'auto'])
@pytest.mark.parametrize('channel', ['materials', 'update', 'materialIds', 'updateMaterialIds', 'shared'])
async def test_pending_material_receipt_waits_for_confirmation_then_covers_actual_binding(setup, mode, channel):
    from app.agent.actions.interactions import finish_waiting
    context, work, values, card = await pending_material_write(setup, mode, channel)
    assert card['objectId'] == work['id']
    assert card['materialSources'] == values
    assert not card.get('remainingChanges')
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        selected = collections(job)[0]
        assert uncovered(selected, [card]) == values  # Approval is not a saved receipt.
        assert uncovered(selected, [card], include_pending=True) == []
        assert uncovered(selected, [{**card, 'objectId': 'another-work'}], include_pending=True) == values
        assert uncovered(selected, [{**card, 'taskItemId': 'another-task'}], include_pending=True) == values
        assert uncovered(selected, [{**card, 'canConfirm': False}], include_pending=True) == values
        assert uncovered(selected, [{**card, 'materialSources': []}], include_pending=True) == values
    assert await finish_waiting(context)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        outcome = derive(job, [card], interpretation={'state': 'completed', 'remaining': []})
        assert outcome['state'] == 'needs_confirmation', outcome
        assert outcome['reason'] == ''
        assert outcome['remaining'] == ['更新工作等待确认']
    response = await setup[3]['employee'].post('/api/v1/business-actions/' + card['id'] + '/confirm',
        json={'expectedRevision': card['revision']})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['state'] == 'succeeded'
    assert saved['materialSources'] == values
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert uncovered(collections(job)[0], [saved]) == []
        assert derive(job, [saved], interpretation={'state': 'completed', 'remaining': []})['state'] == 'completed'
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(
            WorkMaterial.work_id == work['id'])) == (2 if channel in ('materialIds', 'updateMaterialIds') else 1)


@pytest.mark.parametrize('mode', ['ask', 'auto'])
async def test_cancelled_material_confirmation_does_not_cover_selected_sources(setup, mode):
    from app.agent.actions.interactions import finish_waiting
    context, work, values, card = await pending_material_write(setup, mode, 'materials')
    assert await finish_waiting(context)
    response = await setup[3]['employee'].post('/api/v1/business-actions/' + card['id'] + '/cancel',
        json={'expectedRevision': card['revision']})
    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert cancelled['state'] == 'cancelled'
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert uncovered(collections(job)[0], [cancelled], include_pending=True) == values
        assert derive(job, [cancelled], interpretation={'state': 'completed', 'remaining': []})['state'] != 'completed'
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.work_id == work['id'])) == 0


@pytest.mark.parametrize('channel', ['materialIds', 'updateMaterialIds'])
async def test_full_existing_material_references_cover_only_the_selected_sources(setup, channel):
    context, work, values, card = await pending_material_write(setup, 'full', channel, confirmation=False)
    assert card['state'] == 'succeeded'
    assert card['materialSources'] == values
    assert not card.get('remainingChanges')
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert uncovered(collections(job)[0], [card]) == []
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.work_id == work['id'])) == 2


@pytest.mark.parametrize('mode,answer_channel,initial_rejection', [
    ('ask', 'panel', ''), ('auto', 'panel', ''), ('full', 'panel', ''), ('full', 'natural', ''),
    ('full', 'panel', 'fields'), ('full', 'panel', 'fields-empty'), ('full', 'panel', 'legacy-other'),
])
async def test_worker_destination_panel_discards_candidate_fields_and_resumes_exact_materials(setup, monkeypatch, mode, answer_channel, initial_rejection):
    """Fixed model inputs through HTTP/worker; not live model quality evidence."""
    from langchain_openai import ChatOpenAI
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from pydantic import Field
    from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    from app.tasks.context import RunContext
    from app.tasks.processing import handlers
    from app.tasks.runtime.queue import claim
    from _support.agent.business_actions import create
    from _support.http.company import keyed

    context, sent = await mode_runtime(setup, mode, '之前的都添加到我的工作里面')
    values = await seed_files(context)
    source_message = sent['messageId']
    if initial_rejection == 'legacy-other':
        class LegacyJudge:
            async def ainvoke(self, messages):
                return AIMessage(content=json.dumps({'allowed': False, 'quote': '之前的都添加到我的工作里面',
                    'reason': '候选工作缺少正文', 'failureKind': 'invalid_arguments', 'denialScope': 'fields',
                    'requiredFields': ['body']}))
        context.intent_model = LegacyJudge()
        old = await execute(context, step=1, action='create_work', changes={'title': '资料整理', 'materials': values[:2]})
        assert old['state'] == 'failed'
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.state = 'failed'
        repeated = await setup[3]['employee'].post('/api/v1/messages', json={
            'conversationId': sent['conversationId'], 'text': '之前的都添加到我的工作里面'}, headers=keyed())
        assert repeated.status_code == 202, repeated.text
        sent = repeated.json()
        job = await claim(context.sessions, context.owner_id)
        context = RunContext(job.owner_id, job.company_id, job.id, job.fence,
            context.sessions, context.settings, source_revision=0)
    work = await create(setup[3]['employee'], '资料整理')
    original_context = handlers.RunContext
    def with_plan(*args, **kwargs):
        result = original_context(*args, **kwargs)
        result.work_change_model = kwargs['intent_model']
        return result
    monkeypatch.setattr(handlers, 'RunContext', with_plan)

    class DestinationModel(ChatOpenAI):
        resumed: bool = False
        calls: int = 0
        checks: int = 0
        plans: list = Field(default_factory=list)
        async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
            try:
                payload = json.loads(input[-1].content) if isinstance(input, list) else {}
            except (ValueError, TypeError):
                payload = {}
            if payload.get('task') == 'work_change_plan':
                self.plans.append(payload)
                fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
                # Reproduce the bad candidate plan before any destination consent.
                for name in (['materials'] if self.resumed else ['body', 'materials']):
                    fields[name] = {'mode': 'set', 'value': None,
                        'quotes': [{'messageId': sent['messageId'], 'text': '之前的都添加到我的工作里面'}]}
                return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(fields))))
            if payload.get('proposedOperation'):
                self.checks += 1
                saved = payload.get('materialCollections') or payload['conversationTask'].get('previousTask', {}).get('materialCollections', [])
                selection = {'mode': 'previous', 'previousId': saved[0]['id']} if self.resumed else {
                    'mode': 'all', 'quote': payload['currentUserText']}
                # The judge repeats the real false positive: an authentic but
                # generic My Work quote must not select the sole read record.
                selection.update(destination='existing', targetId=work['id'],
                    destinationEvidence=({'source': 'interaction'} if answer_channel == 'panel'
                        else destination_quote(payload)) if self.resumed else destination_quote(payload))
                assert 'destinationQuestions' not in payload
                # After the repeated request opens its own question, its exact
                # user instruction is the advertised continuation source.
                verdict = {'allowed': True, 'quote': '之前的都添加到我的工作里面',
                    'quoteMessageId': sent['messageId'] if self.resumed else source_message,
                    'resumeTask': self.resumed, 'reason': '',
                    'requiredFields': ['materials'], 'requestedChanges': [{'field': 'materials', 'kind': 'material',
                        'quote': '之前的都添加到我的工作里面'}],
                    'receiptOnly': True, 'materialSelection': selection}
                if initial_rejection and not self.resumed:
                    verdict.update(allowed=False, failureKind='invalid_arguments', recoveryOwner='assistant',
                        denialScope='other' if initial_rejection == 'legacy-other' else 'fields',
                        reason='候选工作缺少正文，请助手补齐后执行。',
                        requiredFields=[] if initial_rejection == 'fields-empty' else ['title', 'materials'],
                        requestedChanges=[], resumeTask=initial_rejection == 'legacy-other')
                    selection.update(destination='new', targetId='')
                    if initial_rejection == 'legacy-other':
                        previous = payload['conversationTask']['previousTask']
                        assert previous['items'][0]['action'] == 'create_work'
                        assert not previous['items'][0].get('receiptId')
                        verdict['taskItemId'] = previous['items'][0]['id']
                        selection['messageId'] = source_message
                if payload.get('workChangePlan'):
                    for name in ('requiredFields', 'requestedChanges'):
                        verdict.pop(name)
                    verdict['invalidFields'] = []
                return AIMessage(content=json.dumps(verdict))
            return await super().ainvoke(input, config, stop=stop, **kwargs)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            steps = [('load_tools', {'groups': ['work']}),
                     ('get_work_item', {'work_id': work['id']}),
                     ('execute_business_action', {'step': 1, 'action': 'update_work',
                        'target_id': work['id'], 'expected_revision': 1, 'changes': {'materials': values}})]
            if initial_rejection and not self.resumed:
                steps[-1] = ('execute_business_action', {'step': 1, 'action': 'create_work',
                    'changes': {'title': '资料整理', 'materials': values}})
            assert self.calls <= len(steps), 'A known destination gap must not require another model rewrite'
            name, args = steps[self.calls - 1]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                'id': f'destination-{self.calls}', 'name': name, 'args': args}]))])

    async def run(job, *, resumed=False):
        model = DestinationModel(model='controlled-destination', api_key='test-no-network',
            base_url='http://127.0.0.1:1', max_retries=0, resumed=resumed)
        async with AsyncPostgresSaver.from_conn_string(context.settings.checkpoint_url) as saver:
            await handlers.process_job(job, context.sessions, context.settings, saver, model=model)
        return model
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    first = await run(job)
    response = await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])
    message = response.json()
    async with context.sessions() as db:
        diagnosed = await db.get(Job, sent['jobId'])
        assert message['job']['state'] == 'awaiting_input', (diagnosed.error, diagnosed.result.get('nodeExecution'))
    assert first.calls == 3 and first.checks == 1
    assert len(first.plans) == (0 if initial_rejection else 1)
    panel = message['interactions'][0]
    assert len(panel['questions']) == 1
    question = panel['questions'][0]
    assert question['prompt'] == '这 11 份文件要保存到哪里？'
    assert question['allowCustom']
    assert {option['id'] for option in question['options']} == {'work-' + work['id'], 'new'}
    assert (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['interactions'] == message['interactions']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        if not initial_rejection:
            assert set(job.result['workChangeCandidates']['targets'][work['id']]['fields']) == {'body', 'materials'}
        assert not job.result.get('workChangeRequirements')
        assert not any('正文' in item for item in job.result['taskOutcome']['remaining'])
        assert job.result['taskOutcome']['nextAction'] == 'reply'
        assert len(collections(job)) == 1
        assert len(collections(job)[0]['sources']) == 11
        assert collections(job)[0]['destination'] == 'unselected'
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))
        original_body = (await db.get(WorkItem, work['id'])).content['body']
    payload = ({'expectedRevision': panel['revision'], 'answers': [{'questionId': question['id'], 'optionIds': ['work-' + work['id']]}]}
        if answer_channel == 'panel' else {'conversationId': sent['conversationId'], 'text': '就放现有那条'})
    endpoint = '/api/v1/interactions/' + panel['id'] + '/answer' if answer_channel == 'panel' else '/api/v1/messages'
    headers = keyed()
    answered = await setup[3]['employee'].post(endpoint, json=payload, headers=headers)
    assert answered.status_code == (200 if answer_channel == 'panel' else 202), answered.text
    repeated = await setup[3]['employee'].post(endpoint, json=payload, headers=headers)
    assert repeated.status_code == answered.status_code and repeated.json() == answered.json()
    next_job = await claim(context.sessions, context.owner_id)
    second = await run(next_job, resumed=True)
    async with context.sessions() as db:
        live = await db.get(Job, next_job.id)
        assert live.state == ('awaiting_input' if mode == 'ask' else 'succeeded'), json.dumps({
            'error': live.error, 'outcomes': live.result.get('toolOutcomes'),
            'nodes': live.result.get('nodeExecution'), 'snapshot': live.result.get('taskSnapshot'),
            'taskItems': live.result.get('taskItems')}, ensure_ascii=False)
        assert second.calls == 3 and second.checks == 1 and len(second.plans) == 1
        assert set(live.result['workChangeRequirements']['targets'][work['id']]['fields']) == {'materials'}
        action = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == next_job.target_id))
        assert action and action.state == ('pending' if mode == 'ask' else 'succeeded')
    if mode == 'ask':
        confirmed = await setup[3]['employee'].post('/api/v1/business-actions/' + action.id + '/confirm',
            json={'expectedRevision': action.revision})
        assert confirmed.status_code == 200 and confirmed.json()['state'] == 'succeeded', confirmed.text
    async with context.sessions() as db:
        current = await db.get(WorkItem, work['id'])
        assert current.content['body'] == original_body
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.work_id == work['id'])) == 11


async def test_destination_question_merges_independent_gaps_and_preserves_success_and_remaining(setup):
    import asyncio
    from dataclasses import replace
    from app.agent.actions.interactions import ask, finish_waiting
    from app.agent.actions.material_questions import ask_destination
    from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan
    from app.modules.interactions.models import AssistantInteraction
    from _support.agent.business_actions import create, read_work
    context, sent = await mode_runtime(setup, 'full', '把资料整理的状态改为已完成，补充正文：客户资料，把第一份和第二份文件分别保存到不同工作，另一个报告日期等我补充')
    work = await create(setup[3]['employee'], '资料整理')
    values = await seed_files(context, 2)
    class ChangeJudge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            if payload.get('task') == 'work_change_plan':
                fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
                fields['status'] = {'mode': 'set', 'value': 'done', 'quotes': [{'messageId': sent['messageId'], 'text': '状态改为已完成'}]}
                fields['body'] = {'mode': 'set', 'value': None, 'quotes': [{'messageId': sent['messageId'], 'text': '补充正文：客户资料'}]}
                return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(fields))))
            return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '',
                'invalidFields': [],
                'taskContext': {'state': 'needs_input', 'remaining': ['报告日期尚待补充']}}))
    context.intent_model = context.work_change_model = ChangeJudge()
    await read_work(context, work['id'])
    saved = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'status': 'done'})
    assert saved['state'] == 'succeeded', saved
    context.work_change_model, context.intent_model = None, AllJudge(destination='unselected')
    asked = await ask(context, [{'id': 'date', 'prompt': '报告用哪一天？', 'type': 'text'}])
    for step, selected in [(2, values[:1]), (3, values[1:])]:
        # Two independently selected collections; fixed judge supplies exact sources.
        class SelectedJudge(AllJudge):
            async def ainvoke(self, messages):
                response = json.loads((await super().ainvoke(messages)).content)
                response.update(taskItemId='', newTaskItem=True)
                response['materialSelection'] = {'mode': 'selected', 'quote': '第一份' if step == 2 else '第二份',
                    'references': selected, 'destination': 'unselected'}
                return AIMessage(content=json.dumps(response))
        context.intent_model = SelectedJudge()
        result = await execute(context, step=step, action='create_work', changes={'title': f'未选择的资料工作 {step}', 'materials': selected})
        assert result['state'] == 'waiting', result
    first, again = await asyncio.gather(ask_destination(context), ask_destination(replace(context)))
    assert first['interactionId'] == again['interactionId'] == asked['interactionId']
    assert await finish_waiting(context)
    message = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert len(message['interactions']) == 1
    assert len(message['interactions'][0]['questions']) == 3
    assert message['interactions'][0]['questions'][0]['id'] == 'date'
    async with context.sessions() as db:
        live = await db.get(Job, context.job_id)
        assert '报告日期尚待补充' in live.result['taskOutcome']['remaining']
        assert any('工作正文' in item for item in live.result['taskOutcome']['remaining'])
        assert set(live.result['workChangeRequirements']['targets'][work['id']]['fields']) == {'status', 'body'}
        assert live.result['taskOutcome']['completed']
        assert len(collections(live)) == 2
        assert not await db.scalar(select(AssistantInteraction.id).where(AssistantInteraction.message_id == sent['messageId'], AssistantInteraction.state == 'expired'))


@pytest.mark.parametrize('failure,scope,fields,not_requested,quote,target', [
    ('not_requested', 'authorization', ['body'], False, True, False),
    ('invalid_arguments', 'fields', ['body'], True, True, False),
    ('permission_denied', 'fields', ['body'], False, True, False),
    ('conflict', 'fields', ['body'], False, True, False),
    ('invalid_arguments', 'authorization', ['body'], False, True, False),
    ('invalid_arguments', 'source', ['body'], False, True, False),
    ('invalid_arguments', 'other', [], False, True, False),
    ('invalid_arguments', 'fields', ['body'], False, False, False),
    ('invalid_arguments', 'fields', ['body'], False, True, True),
])
async def test_destination_precedence_does_not_replace_other_refusals_or_real_field_gaps(
        setup, failure, scope, fields, not_requested, quote, target):
    from app.agent.actions.material_questions import ask_destination
    from app.modules.interactions.models import AssistantInteraction
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    text = '新建一条工作，把之前的文件都放进去' if target else '之前的都添加到我的工作里面'
    context, sent = await mode_runtime(setup, 'full', text)
    values = await seed_files(context, 2)
    class DeniedJudge(AllJudge):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            value = json.loads(response.content)
            value.update(allowed=False, notRequested=not_requested, failureKind=failure, denialScope=scope,
                         requiredFields=fields, quote=text if quote else '不属于当前用户的原话', reason='受控拒绝')
            return AIMessage(content=json.dumps(value))
    context.intent_model = DeniedJudge(destination='new')
    result = await execute(context, step=1, action='create_work', changes={'title': '资料整理', 'materials': values})
    assert result['state'] != 'clarification', result
    assert result.get('category', result['state']) == ('not_requested' if not_requested else failure), result
    assert await ask_destination(context) is None
    assert len(context.intent_model.inputs) == 1
    async with context.sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert not job.result.get('workChangeRequirements')
        for model in (AssistantInteraction, BusinessAction, WorkItem, WorkMaterial):
            assert not await db.scalar(select(model.id).where(model.owner_id == context.owner_id))


async def test_destination_precedence_does_not_hide_invalid_material_sources(setup):
    from fastapi import HTTPException
    from app.agent.actions.material_questions import ask_destination
    context, sent = await mode_runtime(setup, 'full', '之前的都添加到我的工作里面')
    values = await seed_files(context, 2)
    class InvalidSourceJudge(AllJudge):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            value = json.loads(response.content)
            value.update(allowed=False, failureKind='invalid_arguments', denialScope='fields', requiredFields=['body'])
            value['materialSelection'].update(mode='selected', references=[{**values[0], 'deliverableId': str(uuid4())}])
            return AIMessage(content=json.dumps(value))
    context.intent_model = InvalidSourceJudge(destination='new')
    with pytest.raises(HTTPException) as error:
        await execute(context, step=1, action='create_work', changes={'title': '资料整理', 'materials': values})
    assert error.value.status_code in (403, 404)
    assert await ask_destination(context) is None
    async with context.sessions() as db:
        assert not collections(await db.get(Job, sent['jobId']))


async def test_worker_unread_candidates_allow_natural_new_destination_without_naming(setup):
    from langchain_openai import ChatOpenAI
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    from app.tasks.processing.handlers import process_job
    from app.tasks.runtime.queue import claim
    from _support.agent.business_actions import create
    from _support.http.company import keyed
    context, sent = await mode_runtime(setup, 'full', '之前的都添加到我的工作里面')
    values = await seed_files(context)
    unread = await create(setup[3]['employee'], '未读取且未选择的唯一工作')
    class NaturalDestinationModel(ChatOpenAI):
        resumed: bool = False
        calls: int = 0
        async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
            try:
                payload = json.loads(input[-1].content) if isinstance(input, list) else {}
            except (ValueError, TypeError):
                payload = {}
            if payload.get('proposedOperation'):
                selected = payload.get('materialCollections') or payload['conversationTask'].get('previousTask', {}).get('materialCollections', [])
                selection = {'mode': 'previous', 'previousId': selected[0]['id']} if self.resumed else {
                    'mode': 'all', 'quote': payload['currentUserText']}
                # A generic first request cannot mean new merely because the
                # proposal is create_work. A later explicit new reply can.
                selection.update(destination='new', destinationEvidence=destination_quote(payload))
                return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '',
                    'resumeTask': self.resumed, 'receiptOnly': True, 'materialSelection': selection}))
            return await super().ainvoke(input, config, stop=stop, **kwargs)
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            assert self.calls <= 2, 'Do not force a candidate read or rewrite a deterministic question'
            name, args = ('load_tools', {'groups': ['work']}) if self.calls == 1 else (
                'execute_business_action', {'step': 1, 'action': 'create_work', 'changes': {'title': '文件归档', 'materials': values}})
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                'id': f'natural-{self.calls}', 'name': name, 'args': args}]))])
    async def run(job, resumed=False):
        model = NaturalDestinationModel(model='controlled-natural', api_key='test-no-network',
            base_url='http://127.0.0.1:1', max_retries=0, resumed=resumed)
        async with AsyncPostgresSaver.from_conn_string(context.settings.checkpoint_url) as saver:
            await process_job(job, context.sessions, context.settings, saver, model=model)
        assert model.calls == 2
    async with context.sessions() as db:
        await run(await db.get(Job, context.job_id))
    message = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['job']['state'] == 'awaiting_input', message['job']
    panel = message['interactions'][0]
    assert len(panel['questions']) == 1
    assert [option['id'] for option in panel['questions'][0]['options']] == ['new']
    assert panel['questions'][0]['allowCustom']
    answer = await setup[3]['employee'].post('/api/v1/messages', json={
        'conversationId': sent['conversationId'], 'text': '另建一条保存这些文件就好'}, headers=keyed())
    assert answer.status_code == 202, answer.text
    job = await claim(context.sessions, context.owner_id)
    await run(job, resumed=True)
    response = (await setup[3]['employee'].get('/api/v1/messages/' + job.target_id)).json()
    assert response['job']['state'] == 'succeeded', response['job']
    async with context.sessions() as db:
        action = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id))
        assert action.state == 'succeeded'
        assert action.result['objectId'] != unread['id']
        assert await db.scalar(select(func.count()).select_from(WorkMaterial).where(WorkMaterial.work_id == action.result['objectId'])) == 11
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == context.owner_id)) == 2
    original = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert original['interactions'][0]['state'] == 'answered'


@pytest.mark.parametrize('text', ['不要新建工作，先看看这些材料', '如果以后需要再新建工作，今天只讨论材料'])
async def test_grounded_work_reference_cannot_override_semantic_refusal(setup, text):
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    context, _ = await mode_runtime(setup, 'full', text)
    values = await seed_files(context, 1)
    class RefusingJudge(AllJudge):
        async def ainvoke(self, messages):
            result = json.loads((await super().ainvoke(messages)).content)
            result.update(allowed=False, notRequested=True, failureKind='not_requested', reason='本次未要求新建工作')
            return AIMessage(content=json.dumps(result))
    context.intent_model = RefusingJudge(destination='new')
    result = await execute(context, step=1, action='create_work', changes={'title': '资料工作', 'materials': values})
    assert result['state'] == 'not_requested', result
    async with context.sessions() as db:
        for model in (WorkItem, WorkMaterial, BusinessAction):
            assert await db.scalar(select(func.count()).select_from(model).where(model.owner_id == context.owner_id)) == 0


async def test_destination_panel_evidence_is_current_task_collection_and_revision_bound(setup):
    from fastapi import HTTPException
    from app.agent.actions.interactions import finish_waiting
    from app.agent.actions.material_questions import ask_destination
    from app.agent.actions.material_selection import destination_questions
    from app.agent.context.task_context import projection
    from app.modules.interactions.models import AssistantInteraction
    from app.modules.work.models import WorkItem
    from app.tasks.context import RunContext
    from app.tasks.runtime.queue import claim
    from _support.agent.business_actions import create, read_work
    from _support.http.company import keyed
    context, sent = await mode_runtime(setup, 'full', '把全部文件添加到我的工作')
    values = await seed_files(context, 1)
    work = await create(setup[3]['employee'], '资料整理')
    await read_work(context, work['id'])
    context.intent_model = AllJudge(destination='new')
    assert (await execute(context, step=1, action='create_work', changes={'title': '资料', 'materials': values}))['state'] == 'waiting'
    panel = await ask_destination(context)
    assert await finish_waiting(context)
    response = await setup[3]['employee'].post('/api/v1/messages',
        json={'conversationId': sent['conversationId'], 'text': '就放现有那条'}, headers=keyed())
    assert response.status_code == 202, response.text
    claimed = await claim(context.sessions, context.owner_id)
    next_context = RunContext(claimed.owner_id, claimed.company_id, claimed.id, claimed.fence,
        context.sessions, context.settings, source_revision=0)
    async with context.sessions.begin() as db:
        from app.tasks.lease import lease
        job, actor = await lease(db, next_context)
        message = await db.get(Message, job.target_id)
        task = await projection(db, actor, job, message, next_context)
        request = {'conversationTask': task}
        expected = await destination_questions(db, actor, job, message, request)
        assert len(expected) == 1 and expected[0]['options'][0]['objectId'] == work['id']
        row = await db.get(AssistantInteraction, panel['interactionId'])
        for state in ('cancelled', 'expired', 'answered'):
            row.state = state
            assert await destination_questions(db, actor, job, message, request) == []
        row.state = 'waiting'
        original_task = row.task_id
        row.task_id = 'another-task'
        assert await destination_questions(db, actor, job, message, request) == []
        row.task_id = original_task
        unrelated = {'conversationTask': {**task, 'previousTask': {**task['previousTask'], 'materialCollections': []}}}
        assert await destination_questions(db, actor, job, message, unrelated) == []
        record = await db.get(WorkItem, work['id'])
        record.revision += 1
        with pytest.raises(HTTPException) as error:
            await destination_questions(db, actor, job, message, request)
        assert error.value.status_code == 409
