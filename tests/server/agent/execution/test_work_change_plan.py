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
from _support.agent.business_actions import create, read_work, runtime
from _support.work.work_change_plan import PlanJudge

pytestmark = pytest.mark.asyncio


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
                'appendFields': ['summary'], 'appendValues': {'summary': '名单已确认。'}, 'materialSelection': {'mode': 'none'}})
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
    from _support.agent.assistant_execution import ReceiptJudge
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


@pytest.mark.parametrize('field', ['title', 'summary', 'blocker', 'nextStep'])
async def test_text_plan_schema_rejects_replacement_content_before_semantic_validation(field):
    from pydantic import ValidationError
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    fields[field] = {'mode': 'set', 'quotes': [{'text': '下一步改为周五完成演示文稿'}], 'value': '周五完成演示文稿'}
    with pytest.raises(ValidationError) as error:
        WorkChangePlan.model_validate(fields)
    assert error.value.errors(include_input=False)[0]['loc'] == (field, 'value')


async def test_text_plan_keeps_clear_and_source_checks_with_field_locations():
    payload = {'messageId': 'message', 'userSources': [{'messageId': 'message', 'userText': '清空下一步'}]}
    fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
    fields['nextStep'] = {'mode': 'set', 'quotes': [{'text': '清空下一步'}], 'value': ''}
    plan = validate_plan(WorkChangePlan.model_validate(fields), payload)
    assert patch_error(plan, {'targetContent': {'nextStep': '旧计划'}, 'changes': {'nextStep': ''}}) == ''
    assert 'nextStep 应为' in patch_error(plan, {'changes': {'nextStep': '替换而非清空'}})
    fields['nextStep']['quotes'][0]['text'] = '另一个来源的指令'
    with pytest.raises(ValueError, match=r'nextStep\.quotes: Change source is not original user text'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)
    fields['nextStep']['quotes'] = []
    with pytest.raises(ValueError, match=r'nextStep\.quotes: Each change needs a user source'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)
    fields['nextStep']['mode'] = 'preserve'
    with pytest.raises(ValueError, match=r'nextStep\.value: Preserved/appended field'):
        validate_plan(WorkChangePlan.model_validate(fields), payload)


async def test_text_plan_retry_identifies_value_field_and_writes_only_once(setup):
    from _support.agent.assistant_execution import ReceiptJudge
    work = await create(setup[3]['employee'], '单字段计划', summary='保留说明', nextStep='旧计划')
    context, _ = await runtime(setup, '只把下一步改为周五完成演示文稿，其他内容不变')
    context.node_retry = True
    await initialize(context, 'plan-value-format')
    await read_work(context, work['id'])

    class ValueJudge(PlanJudge):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            if len(self.inputs) == 1:
                result = json.loads(response.content)
                result['nextStep']['value'] = '周五完成演示文稿'
                return AIMessage(content=json.dumps(result))
            assert len(messages) == 3 and 'nextStep.value' in messages[-1].content
            return response

    context.work_change_model = ValueJudge({'nextStep': ('set', '下一步改为周五完成演示文稿', None)})
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '下一步改为周五完成演示文稿', 'field': 'nextStep', 'kind': 'next_action'}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'nextStep': '周五完成演示文稿'})
    result = await execute(context, **args)
    assert result['state'] == 'succeeded'
    assert (await execute(context, **args))['id'] == result['id']
    after = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and after['nextStep'] == '周五完成演示文稿'
    assert all(after[key] == work[key] for key in ('title', 'summary', 'status', 'blocker', 'dueDate', 'body'))
    assert len(context.work_change_model.inputs) == 2


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
    from _support.agent.assistant_execution import ReceiptJudge
    from _support.materials.documents import upload
    from _support.agent.execution_permissions import mode_runtime
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
    from _support.agent.assistant_execution import ReceiptJudge
    from _support.materials.documents import upload
    from _support.agent.execution_permissions import mode_runtime
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
    from _support.agent.assistant_execution import ReceiptJudge
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


async def test_equal_date_is_preserved_on_first_patch_despite_judge_required_field(setup):
    from _support.agent.assistant_execution import ReceiptJudge
    work = await create(setup[3]['employee'], '解除阻碍', status='blocked', dueDate='2026-10-12')
    context, _ = await runtime(setup, '改回进行中，保留2026-10-12截止')
    await read_work(context, work['id'])
    context.work_change_model = PlanJudge({'status': ('set', '改回进行中', 'in_progress'),
                                         'dueDate': ('set', '保留2026-10-12截止', '2026-10-12')})
    context.intent_model = ReceiptJudge(receipt=False, required_fields=['status', 'dueDate'], requested_changes=[
        {'field': 'status', 'kind': 'status', 'quote': '改回进行中'},
        {'field': 'dueDate', 'kind': 'deadline', 'quote': '保留2026-10-12截止'}])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'status': 'in_progress'})
    assert result['state'] == 'succeeded', result
    saved = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['status'] == 'in_progress' and saved['dueDate'] == '2026-10-12' and saved['revision'] == 2


@pytest.mark.parametrize('kind', ['invalid_arguments', 'missing_info', 'permission_denied', 'conflict'])
async def test_cross_group_denial_is_repaired_not_mistaken_for_user_clarification(setup, kind):
    from _support.work.work_records import body
    from app.agent.actions.intent import IntentVerdict
    work = await create(setup[3]['employee'], '补正文')
    context, _ = await runtime(setup, '补充内容：三份反馈，下一步归类。')
    context.node_retry = True
    await initialize(context, 'atomic-body')
    await read_work(context, work['id'])
    context.work_change_model = PlanJudge({'body': ('set', '补充内容：三份反馈', None),
                                         'nextStep': ('set', '下一步归类', None)})
    class Judge:
        calls = 0
        async def ainvoke(self, messages):
            self.calls += 1
            payload = json.loads(messages[1].content)
            if self.calls == 1:
                return AIMessage(content=IntentVerdict(allowed=False, quote=payload['currentUserText'], reason='缺少下一步', failureKind=kind, denialScope='fields',
                    requiredFields=['nextStep'], requestedChanges=[{'field': 'nextStep', 'quote': '下一步归类', 'kind': 'next_action'}]).model_dump_json())
            return AIMessage(content=IntentVerdict(allowed=True, quote=payload['currentUserText'], reason='', requiredFields=['body'],
                requestedChanges=[{'field': 'body', 'quote': '补充内容：三份反馈', 'kind': 'content'}]).model_dump_json())
    context.intent_model = Judge()
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'body': body('三份反馈')})
    assert result['state'] == 'succeeded' and context.intent_model.calls == 2, result
    saved = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['bodyText'] == '三份反馈' and saved['nextStep'] == ''


@pytest.mark.parametrize('repair_allowed', [True, False])
async def test_preserve_conflict_gets_one_independent_recheck_then_normal_authorization(setup, repair_allowed):
    from _support.agent.assistant_execution import ReceiptJudge
    work = await create(setup[3]['employee'], '第二项工作')
    context, _ = await runtime(setup, '把刚才第二项工作的下一步改为今天与负责人确认，第一项不变')
    context.node_retry = True
    await initialize(context, 'scope-repair')
    await read_work(context, work['id'])
    class ScopeJudge:
        calls = 0
        async def ainvoke(self, messages):
            self.calls += 1
            payload = json.loads(messages[1].content)
            assert 'changes' not in payload and 'proposedOperation' not in payload
            fields = {name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS}
            if self.calls == 2 and repair_allowed:
                fields['nextStep'] = {'mode': 'set', 'quotes': [{'messageId': payload['messageId'], 'text': '下一步改为今天与负责人确认'}], 'value': None}
            return AIMessage(content=json.dumps(fields))
    context.work_change_model = ScopeJudge()
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '下一步改为今天与负责人确认', 'field': 'nextStep', 'kind': 'next_action'}])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'nextStep': '今天与负责人确认'})
    first = await execute(context, **args)
    if repair_allowed:
        assert first['state'] == 'succeeded'
        assert (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()['revision'] == 2
    else:
        assert first['category'] == 'invalid_arguments'
        second = await execute(context, **args)
        assert second['category'] == 'invalid_arguments'
        assert (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()['revision'] == 1
    assert context.work_change_model.calls == 2


@pytest.mark.parametrize('exit_at', ['before_node', 'after_node'])
async def test_scope_repair_recovers_same_node_after_worker_exit(setup, monkeypatch, exit_at):
    from app.agent.actions import work_change_plan as module
    from app.tasks.nodes.node_execution import active_node
    context, sent = await runtime(setup, '下一步改为确认负责人')
    context.node_retry = True
    await initialize(context, 'repair-restart')
    payload = {'messageId': sent['messageId'], 'userSources': [{'messageId': sent['messageId'], 'userText': '下一步改为确认负责人'}]}
    plan = WorkChangePlan.model_validate({name: {'mode': 'preserve', 'quotes': [], 'value': None} for name in FIELDS})
    proposal = {'changes': {'nextStep': '确认负责人'}, 'targetContent': {'nextStep': ''}}
    judge = PlanJudge({'nextStep': ('set', '下一步改为确认负责人', None)})
    original = module.execute_node
    calls = []
    async def interrupt_once(*args, **kwargs):
        calls.append((kwargs['identity'], active_node.get()))
        if len(calls) == 1 and exit_at == 'before_node':
            raise InterruptedError('worker exited before durable node')
        result = await original(*args, **kwargs)
        if len(calls) == 1:
            raise InterruptedError('worker exited after durable result, before plan cache')
        return result
    monkeypatch.setattr(module, 'execute_node', interrupt_once)
    for parent in ('first-tool', 'resumed-tool'):
        token = active_node.set((parent, 'tool'))
        try:
            if parent == 'first-tool':
                with pytest.raises(InterruptedError):
                    await module.repair_preserved_scope(context, 'stable-key', plan, payload, proposal, judge)
            else:
                result = await module.repair_preserved_scope(context, 'stable-key', plan, payload, proposal, judge)
        finally:
            active_node.reset(token)
    assert result.nextStep.mode == 'set' and module.patch_error(result, proposal) == ''
    assert calls[0] == calls[1] and len(judge.inputs) == 1
    repeated = await module.repair_preserved_scope(context, 'stable-key', plan, payload, proposal, judge)
    assert repeated == result and len(calls) == 2
