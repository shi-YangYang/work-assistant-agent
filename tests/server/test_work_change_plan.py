"""Independent work-edit intent, patch repair and preserved record boundaries."""
import json

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import select, func

from app.agent.actions.operations import execute
from app.agent.actions.intent import IntentVerdict, requested_field_contract
from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, operation_fields, source_input, validate_plan, patch_error
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from test_business_actions import create, read_work, runtime

pytestmark = pytest.mark.asyncio


class PlanJudge:
    def __init__(self, fields):
        self.fields, self.inputs = fields, []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        assert 'proposedOperation' not in payload and 'changes' not in payload
        result = {field: {'mode': 'preserve', 'quotes': [], 'value': None} for field in FIELDS}
        for field, (mode, quote, value) in self.fields.items():
            result[field] = {'mode': mode, 'quotes': [{'messageId': payload['messageId'], 'text': quote}], 'value': value}
        return AIMessage(content=json.dumps(result))


async def test_independent_plan_blocks_missing_and_wrong_status_then_appends_once(setup, monkeypatch):
    clients = setup[3]
    work = await create(clients['employee'], '新人培训', summary='为8名新员工准备入职培训。', dueDate='2026-10-09')
    context, sent = await runtime(setup, '更新新人培训：名单已确认，但讲师时间还没定，请记成有阻碍，下一步是找讲师确认时间。')
    context.node_retry, context.intent_model = True, None
    await initialize(context, 'independent-coverage')
    await read_work(context, work['id'])
    plan = PlanJudge({'summary': ('append', '名单已确认', None), 'blocker': ('set', '讲师时间还没定', None),
                      'status': ('set', '请记成有阻碍', 'blocked'), 'nextStep': ('set', '下一步是找讲师确认时间', None)})
    calls = []
    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}, 'baseUrl': 'https://example.com'}, 'test'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    async def chat(settings, config, key, messages, *, on_event, **kwargs):
        payload = json.loads(messages[-1]['content'])
        calls.append(payload)
        await on_event('started')
        if payload.get('task') == 'work_change_plan':
            output = (await plan.ainvoke([AIMessage(content=json.dumps(payload))])).content
        else:
            assert payload['workChangePlan']['status']['value'] == 'blocked'
            output = json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '', 'requiredFields': ['summary', 'blocker', 'status', 'nextStep'],
                'requestedChanges': [{'quote': quote, 'field': field, 'kind': kind} for field, quote, kind in [('summary', '名单已确认', 'progress'), ('blocker', '讲师时间还没定', 'obstacle'), ('status', '请记成有阻碍', 'status'), ('nextStep', '下一步是找讲师确认时间', 'next_action')]],
                'appendFields': ['summary'], 'appendValues': {'summary': '名单已确认。'}})
        return {'choices': [{'message': {'role': 'assistant', 'content': output}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    changes = dict(summary='名单已确认。', blocker='讲师时间尚未确定', nextStep='找讲师确认时间')
    missing = await execute(context, **args, changes=changes)
    assert missing['category'] == 'invalid_arguments' and 'status' in missing['message']
    wrong = await execute(context, **args, changes={**changes, 'status': 'in_progress'})
    assert wrong['category'] == 'invalid_arguments' and 'blocked' in wrong['message']
    async with context.sessions() as db:
        before = await db.get(WorkItem, work['id'])
        assert before.revision == 1 and before.content['summary'] == work['summary']
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == sent['messageId'])) == 0
    changes['status'] = 'blocked'
    first = await execute(context, **args, changes=changes)
    assert first['state'] == 'succeeded'
    second = await execute(context, **args, changes=changes)
    assert second['id'] == first['id']
    after = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and after['status'] == 'blocked'
    assert after['summary'] == work['summary'] + '\n名单已确认。'
    assert after['blocker'] == changes['blocker'] and after['dueDate'] == '2026-10-09'
    assert len(calls) == 2 and len(plan.inputs) == 1  # one plan, one authorization; retries do not re-plan


async def test_plan_does_not_bypass_explicit_confirmation_or_stale_target(setup):
    from test_assistant_execution import ReceiptJudge
    from app.modules.members.models import Member
    context, sent = await runtime(setup, '仅把期限改为2026-10-11，先给我确认')
    work = await create(setup[3]['employee'], '待审工作', summary='保留说明', dueDate='2026-10-09')
    await read_work(context, work['id'])
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '期限改为2026-10-11', 'field': 'dueDate', 'kind': 'deadline'}])
    context.work_change_model = PlanJudge({'dueDate': ('set', '期限改为2026-10-11', '2026-10-11')})
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'executionMode': 'ask'}
        member = await db.get(Member, context.owner_id)
        member.execution_mode = 'ask'
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    wrong = await execute(context, **args, changes={'dueDate': '2026-10-10'})
    assert wrong['category'] == 'invalid_arguments'
    card = await execute(context, **args, changes={'dueDate': '2026-10-11'})
    assert card['state'] == 'pending'
    async with context.sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        assert row.revision == 1 and row.content['dueDate'] == '2026-10-09'
        row.revision += 1
    with pytest.raises(HTTPException) as error:
        await execute(context, **{**args, 'step': 2}, changes={'dueDate': '2026-10-12'})
    assert error.value.status_code == 409 and len(context.work_change_model.inputs) == 1


async def test_contract_preserves_unrequested_fields_and_requires_complete_original_sources():
    request = {'currentUserText': '日期改成2026-10-11', 'conversationTask': {'activeDirectives': [], 'previousTask': {'userSources': [{'messageId': 'prior', 'userText': '把下一步替换为联络客户'}]}}, 'conversationForReferenceOnly': [], 'messageTime': '2026-09-30T00:00:00+08:00', 'timezone': 'Asia/Shanghai'}
    proposal = {'targetId': 'work', 'expectedRevision': 1, 'targetContent': {'summary': '旧说明', 'status': 'blocked'}, 'changes': {'summary': '覆盖', 'status': 'done'}}
    payload = source_input(request, proposal, 'now')
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    fields['nextStep'] = {'mode': 'set', 'quotes': [{'messageId': 'prior', 'text': '下一步替换为联络客户'}], 'value': None}
    fields['dueDate'] = {'mode': 'set', 'quotes': [{'messageId': 'now', 'text': '日期改成2026-10-11'}], 'value': '2026-10-11'}
    plan = validate_plan(WorkChangePlan.model_validate(fields), payload)
    assert set(payload['targetWork']) == {'id', 'revision', 'title', 'content'}
    assert all(key in patch_error(plan, proposal) for key in ('summary', 'status', 'nextStep', 'dueDate'))
    with pytest.raises(ValueError):
        WorkChangePlan.model_validate({key: value for key, value in fields.items() if key != 'status'})
    fields['status'] = {'mode': 'set', 'quotes': [{'messageId': 'now', 'text': '已经完成'}], 'value': 'done'}
    with pytest.raises(ValueError, match='original user'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)


async def test_work_status_plan_cannot_invent_archival_state():
    payload = {'messageId': 'message', 'userSources': [{'messageId': 'message', 'userText': '归档这个工作'}]}
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    fields['status'] = {'mode': 'set', 'quotes': [{'text': '归档这个工作'}], 'value': 'archived'}
    with pytest.raises(ValueError, match='normalized'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)


@pytest.mark.parametrize('missing', ['body', 'update', 'materials', 'removeMaterial'])
async def test_record_plan_cannot_silently_default_missing_classification(missing):
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    assert set(WorkChangePlan.model_json_schema()['required']) == set(FIELDS)
    del fields[missing]
    with pytest.raises(ValueError, match=missing):
        WorkChangePlan.model_validate(fields)


async def test_record_plan_contract_is_independent_of_proposed_fields():
    request = {'currentUserText': '更新这项工作', 'conversationTask': {}, 'conversationForReferenceOnly': [],
               'messageTime': '2026-09-30T00:00:00+08:00', 'timezone': 'Asia/Shanghai'}
    proposal = {'action': 'update_work', 'targetId': 'work', 'expectedRevision': 1, 'targetContent': {}}
    payloads = [source_input(request, {**proposal, 'changes': changes}, 'now')
                for changes in ({'status': 'done'}, {'summary': '错误字段'}, {'bodyEdits': []}, {'materials': []})]
    assert all(payload == payloads[0] and payload['recordContract'] for payload in payloads)
    legacy = source_input(request, {**proposal, 'action': 'propose_progress', 'operation': 'update_work'}, 'now')
    assert legacy['recordContract'] is False


async def test_body_and_material_plan_preserves_progress_and_requires_user_sources():
    user = '正文增加客户背景，把选中的文件保存在工作材料中，进展不要变。'
    request = {'currentUserText': user, 'conversationTask': {}, 'conversationForReferenceOnly': [],
               'messageTime': '2026-09-30T00:00:00+08:00', 'timezone': 'Asia/Shanghai'}
    proposal = {'action': 'update_work', 'targetId': 'work', 'expectedRevision': 1, 'targetContent': {},
                'changes': {'bodyEdits': [{'action': 'append', 'blocks': []}], 'materials': [{'attachmentId': 'file'}]}}
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    for name, quote in [('body', '正文增加客户背景'), ('materials', '把选中的文件保存在工作材料中')]:
        fields[name] = {'mode': 'set', 'quotes': [{'messageId': 'now', 'text': quote}], 'value': None}
    payload = source_input(request, proposal, 'now')
    plan = validate_plan(WorkChangePlan.model_validate(fields), payload)
    assert patch_error(plan, proposal) == ''
    extra = {**proposal, 'changes': {**proposal['changes'], 'update': {'action': 'create', 'text': '已完成'}, 'status': 'done'}}
    assert all(name in patch_error(plan, extra) for name in ('update', 'status'))
    fields['update'] = {'mode': 'set', 'quotes': [{'messageId': 'file', 'text': '把工作记为已完成'}], 'value': None}
    with pytest.raises(ValueError, match='original user'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)


@pytest.mark.parametrize('field', ['materials', 'materialIds', 'removeMaterial'])
async def test_material_intent_accepts_binding_and_removal_without_other_fields(field):
    verdict = IntentVerdict(allowed=True, quote='调整这份材料', reason='',
                           requestedChanges=[{'quote': '调整这份材料', 'field': field, 'kind': 'material'}])
    assert requested_field_contract(verdict, 'update_work')
    wrong = verdict.model_copy(update={'requestedChanges': [verdict.requestedChanges[0].model_copy(update={'field': 'status'})]})
    assert not requested_field_contract(wrong, 'update_work')


async def test_independent_record_steps_do_not_require_mutually_exclusive_changes():
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    for name in ('body', 'update', 'materials', 'removeMaterial'):
        fields[name] = {'mode': 'set', 'quotes': [{'text': '保存内容并整理材料'}], 'value': None}
    plan = WorkChangePlan.model_validate(fields)
    for field, value in [('bodyEdits', []), ('update', {'action': 'create', 'text': '新进展'}),
                         ('materials', [{'attachmentId': 'file'}]), ('removeMaterial', {'id': 'old', 'expectedRevision': 1})]:
        proposal = {'changes': {field: value}}
        assert patch_error(plan, proposal) == ''
        assert operation_fields(plan, proposal) == {'body' if field == 'bodyEdits' else field}
        assert 'status 未要求修改' in patch_error(plan, {'changes': {field: value, 'status': 'done'}})


async def test_body_companion_materials_must_be_referenced_by_edited_blocks():
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    fields['body'] = {'mode': 'set', 'quotes': [{'text': '正文插入选中的图片'}], 'value': None}
    plan = WorkChangePlan.model_validate(fields)
    changes = {'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'material', 'attrs': {'materialId': 'chosen'}}]}],
               'materials': [{'attachmentId': 'chosen'}]}
    assert patch_error(plan, {'changes': changes}) == ''
    assert operation_fields(plan, {'changes': changes}) == {'body'}
    for extra in ({'materials': [*changes['materials'], {'attachmentId': 'unrequested'}]}, {'materialIds': ['unrequested']}):
        assert 'materials 未要求修改' in patch_error(plan, {'changes': {**changes, **extra}})


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_body_and_material_classification_honors_modes_without_extra_progress(setup, mode):
    from test_assistant_execution import ReceiptJudge
    from test_documents import upload
    from test_execution_permissions import mode_runtime
    client = setup[3]['employee']
    work = await create(client, '客户方案')
    context, _ = await mode_runtime(setup, mode, '正文补充客户背景，保存选中的附件，进展与状态不变')
    attachment = await upload(client, 'brief.txt', b'customer background', 'text/plain')
    context.work_change_model = PlanJudge({'body': ('set', '正文补充客户背景', None), 'materials': ('set', '保存选中的附件', None)})
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '正文补充客户背景', 'field': 'bodyEdits', 'kind': 'content'},
                                                          {'quote': '保存选中的附件', 'field': 'materials', 'kind': 'material'}])
    await read_work(context, work['id'])
    changes = {'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '客户背景'}]}]}],
               'materials': [{'attachmentId': attachment['id']}]}
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1}
    rejected = await execute(context, **args, changes={**changes, 'status': 'done'})
    assert rejected['category'] == 'invalid_arguments'
    result = await execute(context, **args, changes=changes)
    assert result['state'] == ('pending' if mode == 'ask' else 'succeeded'), result
    if mode == 'ask':
        before = (await client.get('/api/v1/work-items/' + work['id'])).json()
        assert before['revision'] == 1 and before['bodyText'] == '' and before['materialIds'] == []
        confirmed = await client.post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
        assert confirmed.status_code == 200 and confirmed.json()['state'] == 'succeeded', confirmed.text
    repeated = await execute(context, **args, changes=changes)
    assert repeated['id'] == result['id']
    after = (await client.get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and after['bodyText'] == '客户背景' and after['status'] == work['status']
    assert after['summary'] == '' and len(after['materialIds']) == 1
    assert (await client.get('/api/v1/work-items/' + work['id'] + '/updates')).json()['items'] == []


async def test_body_material_and_progress_steps_keep_separate_receipts_and_replay(setup):
    from test_assistant_execution import ReceiptJudge
    from test_documents import upload
    from test_execution_permissions import mode_runtime
    client = setup[3]['employee']
    work = await create(client, '分步保存')
    context, _ = await mode_runtime(setup, 'full', '保存正文方案，附上选中的文件，再记一条进展：客户已确认。')
    attachment = await upload(client, 'brief.txt', b'customer brief', 'text/plain')
    quotes = [('body', '保存正文方案', 'content'), ('materials', '附上选中的文件', 'material'), ('update', '客户已确认', 'progress')]
    context.work_change_model = PlanJudge({field: ('set', quote, None) for field, quote, _ in quotes})
    context.intent_model = ReceiptJudge(receipt=False, required_fields=[field for field, _, _ in quotes],
                                       requested_changes=[{'quote': quote, 'field': field, 'kind': kind} for field, quote, kind in quotes])
    await read_work(context, work['id'])
    patches = [{'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '正文方案'}]}]}]},
               {'materials': [{'attachmentId': attachment['id']}]}, {'update': {'action': 'create', 'text': '客户已确认'}}]
    receipts = []
    for step, changes in enumerate(patches, 1):
        result = await execute(context, step=step, action='update_work', target_id=work['id'], expected_revision=step, changes=changes)
        assert result['state'] == 'succeeded', result
        receipts.append(result)
    assert len({receipt['id'] for receipt in receipts}) == 3
    assert [item['workChangeFields'] for item in context.intent_model.inputs] == [['body'], ['materials'], ['update']]
    assert [len(item['completedOrPendingSteps']) for item in context.work_change_model.inputs] == [0, 1, 2]
    repeated = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes=patches[0])
    assert repeated['id'] == receipts[0]['id']
    after = (await client.get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 4 and after['bodyText'] == '正文方案' and len(after['materialIds']) == 1
    updates = (await client.get('/api/v1/work-items/' + work['id'] + '/updates')).json()['items']
    assert len(updates) == 1 and updates[0]['text'] == '客户已确认'


@pytest.mark.parametrize('change', ['target_revision', 'cancel'])
async def test_plan_cache_respects_target_version_and_cancelled_lease(setup, change):
    from test_assistant_execution import ReceiptJudge
    from app.tasks.context import LostLease
    work = await create(setup[3]['employee'], '期限安排', dueDate='2026-10-09')
    context, _ = await runtime(setup, '期限改为2026-10-11')
    await read_work(context, work['id'])
    context.work_change_model = PlanJudge({'dueDate': ('set', '期限改为2026-10-11', '2026-10-11')})
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '期限改为2026-10-11', 'field': 'dueDate', 'kind': 'deadline'}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    assert (await execute(context, **args, changes={'dueDate': '2026-10-10'}))['category'] == 'invalid_arguments'
    async with context.sessions.begin() as db:
        if change == 'cancel':
            job = await db.get(Job, context.job_id)
            job.state = 'cancelled'
        else:
            row = await db.get(WorkItem, work['id'])
            row.content = {**row.content, 'summary': '外部补充'}
            row.revision = 2
    if change == 'cancel':
        with pytest.raises(LostLease):
            await execute(context, **args, changes={'dueDate': '2026-10-11'})
        assert len(context.work_change_model.inputs) == 1
        async with context.sessions() as db:
            assert (await db.get(WorkItem, work['id'])).revision == 1
    else:
        await read_work(context, work['id'])
        saved = await execute(context, **{**args, 'expected_revision': 2}, changes={'dueDate': '2026-10-11'})
        assert saved['state'] == 'succeeded' and saved['details']['summary'] == '外部补充'
        assert len(context.work_change_model.inputs) == 2
        assert [item['targetWork']['revision'] for item in context.work_change_model.inputs] == [1, 2]
