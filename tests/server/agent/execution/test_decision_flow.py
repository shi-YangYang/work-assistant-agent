"""Deterministic control boundaries, distinct from the real-provider evaluation."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agent.runtime import decision_flow as flow
from app.agent.runtime.tool_nodes import outcome
from app.agent.runtime.tool_progress.evidence import failed_result, recoverable_result, result_key, reusable_read
from app.agent.tools.resources.documents import read_document
from app.tasks.context import RunContext
from _support.agent.response_delivery import DeliveryModel, run
from _support.agent.fakes import ReviewedFixtureModel


def state():
    context = RunContext('owner', 'company', 'job', 1, None, SimpleNamespace(), source_revision=0)
    return context, SimpleNamespace(result={})


def call(name, identifier, args=None):
    value = {'name': name, 'id': identifier, 'args': args or {}}
    return value, AIMessage(id='batch-' + identifier, content='', tool_calls=[value])


def record(context, job, name, identifier, result, args=None):
    tool, batch = call(name, identifier, args)
    assert flow.begin(context, job, tool, batch, {'need': identifier}) is None
    key = flow.identity(batch, tool)
    message = ToolMessage(name=name, tool_call_id=identifier, content=json.dumps(result))
    returned = flow.end(context, job, {**tool, 'decisionId': key}, message)
    assert json.loads(returned.content)['_flow']['receipt'] == key
    return key


def ready(context, job, evidence, scope='fact', identifier='save'):
    tool, batch = call('save_deliverable', identifier)
    return flow.begin(context, job, tool, batch, {'ready': evidence, 'scope': scope})


@pytest.mark.parametrize('name,args,result,scope', [
    ('find_documents', {}, {'items': [{'name': '预算.docx'}]}, 'fact'),
    ('read_document', {}, {'sourceComplete': True, 'readScope': {'allExtractedTextReturned': False}}, 'full'),
    ('read_document', {}, {'sourceComplete': False, 'readScope': {'allExtractedTextReturned': True}}, 'full'),
    ('read_document', {}, {'sourceComplete': True, 'readScope': {'allExtractedTextReturned': True, 'limitationsCodes': ['visuals_not_read']}}, 'full'),
    ('web_fetch', {}, {'state': 'unavailable', 'url': 'https://example.org'}, 'link'),
    ('web_search', {}, {'items': [{'url': 'https://example.org'}]}, 'full'),
    ('read_images', {}, {'state': 'listed', 'items': [{'id': 'image'}]}, 'full'),
    ('read_images', {'attachment_ids': ['document']}, {'state': 'document_pages', 'items': [{'id': 'document'}]}, 'fact'),
    ('read_document', {'view': 'pages'}, {'status': 'ready', 'pageRefs': ['rendered-page']}, 'fact'),
    ('read_images', {'attachment_ids': ['image']}, {'images': [{'complete': False}], 'text': 'partial'}, 'full'),
    ('execute_business_action', {}, {'state': 'running', 'id': 'action'}, 'fact'),
])
def test_success_directory_partial_or_pending_is_not_proof_of_required_scope(name, args, result, scope):
    context, job = state()
    receipt = record(context, job, name, 'read', result, args)
    assert ready(context, job, [receipt], scope) is None
    assert flow.current(context, job)['phase'] == 'exploring'


def test_ready_ends_exploration_but_keeps_necessary_execution_and_real_recovery():
    context, job = state()
    receipt = record(context, job, 'read_document', 'facts', {'sourceComplete': True,
        'readScope': {'allExtractedTextReturned': True, 'limitationsCodes': []}, 'items': [{'text': '预算12800，交付11月6日'}]})
    assert ready(context, job, [receipt], 'full') is None
    names = {'web_search', 'read_document', 'save_deliverable', 'run_python', 'request_user_input', 'get_business_actions'}
    assert flow.available(flow.current(context, job), names) == names - {'web_search', 'read_document'}
    tool, batch = call('web_search', 'more')
    assert json.loads(flow.begin(context, job, tool, batch, {'need': '再确认一下'}).content)['code'] == 'exploration_closed'
    tool, batch = call('read_document', 'invented')
    assert flow.begin(context, job, tool, batch, {'need': '新事实', 'after': 'invented'}) is not None
    # A failed real execution permits a targeted recovery; the need alone cannot.
    tool, batch = call('save_deliverable', 'save')
    key = flow.identity(batch, tool)
    flow.end(context, job, {**tool, 'decisionId': key}, ToolMessage(name='save_deliverable', tool_call_id='save',
        content=json.dumps({'state': 'conflict', 'message': '成果已更新，请读取最新版本后修改'})))
    assert 'read_document' in flow.available(flow.current(context, job), names)
    tool, batch = call('read_deliverable', 'latest')
    assert flow.begin(context, job, tool, batch, {'need': '读取冲突成果的当前版本', 'after': key}) is None
    assert flow.current(context, job)['phase'] == 'recovering'
    unrelated, unrelated_batch = call('web_search', 'unrelated')
    assert flow.begin(context, job, unrelated, unrelated_batch, {'need': '顺便再找找'}) is not None
    flow.end(context, job, {**tool, 'decisionId': flow.identity(batch, tool)}, ToolMessage(
        name=tool['name'], tool_call_id=tool['id'], content=json.dumps({'id': 'latest', 'content': '已更新'})))
    assert flow.current(context, job)['phase'] == 'recovering'
    retry, retry_batch = call('save_deliverable', 'retry')
    assert flow.begin(context, job, retry, retry_batch, {}) is None
    assert flow.current(context, job)['phase'] == 'executing'
    another, another_batch = call('read_deliverable', 'repeat')
    assert flow.begin(context, job, another, another_batch, {'need': '再次确认', 'after': key}) is not None


def test_changed_source_version_cannot_support_stale_ready_claim():
    context, job = state()
    context.read_versions['work'] = 1
    receipt = record(context, job, 'get_work_item', 'old', {'id': 'work', 'version': 1})
    context.read_versions['work'] = 2
    assert ready(context, job, [receipt]) is None
    assert flow.current(context, job)['phase'] == 'exploring'


def test_execution_fallback_question_enters_waiting_without_new_model_call():
    context, job = state()
    record(context, job, 'execute_business_action', 'fallback', {
        'state': 'clarification', 'category': 'missing_info', 'interactionId': 'question'})
    assert flow.current(context, job)['phase'] == 'waiting'


def test_legacy_terminal_receipt_is_not_wrapped_or_invalidated():
    from app.agent.completion.delivery import Delivery
    context, job = state()
    tool, batch = call('finish_task', 'legacy')
    assert flow.begin(context, job, tool, batch, {}) is None
    original = ToolMessage(name='finish_task', tool_call_id='legacy', content=Delivery(
        answer='已完成。', task={'state': 'completed'}, business_requested=False,
        verification_requested=False).model_dump_json())
    returned = flow.end(context, job, {**tool, 'decisionId': flow.identity(batch, tool)}, original)
    assert returned.content == original.content
    assert Delivery.model_validate_json(returned.content).answer == '已完成。'


def test_ready_is_not_a_blanket_failure_clear_or_batch_completion():
    context, job = state()
    receipt = record(context, job, 'web_search', 'links', {'items': [{'url': 'https://example.org', 'snippet': '官方入口'}]})
    other, batch = call('web_fetch', 'pending')
    assert flow.begin(context, job, other, batch, {'need': '必要的第二来源'}) is None
    assert ready(context, job, [receipt], 'link') is None
    assert flow.current(context, job)['phase'] == 'exploring'


@pytest.mark.parametrize('metadata', [{'ready': ['unknown']}, {'ready': ['unknown'], 'scope': 'full'}])
def test_invalid_ready_cannot_reject_execution_or_change_an_existing_phase(metadata):
    context, job = state()
    for phase in ('exploring', 'executing'):
        job.result = {}
        value = flow.current(context, job)
        value['phase'] = phase
        flow.save(job, value)
        tool, batch = call('execute_business_action', phase, {'action': 'update_work', 'changes': {'materials': [{'attachmentId': 'selected'}]}})
        assert flow.begin(context, job, tool, batch, metadata) is None
        assert flow.current(context, job)['phase'] == phase
        assert not flow.current(context, job)['calls'][flow.identity(batch, tool)].get('blocked')


def test_known_file_linking_does_not_require_reading_file_bodies():
    context, job = state()
    context.read_versions['target'] = 4
    work = record(context, job, 'get_work_item', 'target', {'id': 'target', 'revision': 4})
    directory = record(context, job, 'list_work_materials', 'saved', {
        'workId': 'target', 'workRevision': 4, 'items': [{'attachment': {'id': 'already-bound'}}], 'nextCursor': None}, {'work_id': 'target'})
    tool, batch = call('execute_business_action', 'append', {'action': 'update_work', 'target_id': 'target',
        'expected_revision': 4, 'changes': {'materials': [{'attachmentId': 'selected-new'}]}})
    assert flow.begin(context, job, tool, batch, {'ready': [work, directory]}) is None
    assert flow.current(context, job)['phase'] == 'exploring'
    assert not context.document_reads


@pytest.mark.parametrize('tool,args,result', [
    ('read_work_material', {'view': 'pages'}, {'attachment': {'id': 'actual', 'revision': 1}, 'status': 'ready', 'pageRefs': ['prepared']}),
    ('read_document', {'view': 'pages'}, {'status': 'partial', 'pageRefs': ['prepared'], 'errors': [{'page': 2, 'reason': 'missing'}]}),
    ('read_images', {'attachment_ids': ['document']}, {'state': 'document_pages', 'items': [{'id': 'document'}]}),
])
def test_prepared_visual_references_never_prove_delivered_pixels(tool, args, result):
    context, job = state()
    receipt = record(context, job, tool, 'pages', result, args)
    row = flow.current(context, job)['calls'][receipt]
    assert row['kind'] == 'directory'
    assert not flow.supported(row, 'fact', context, job)
    assert not flow.supported(row, 'full', context, job)


@pytest.mark.parametrize('result', [
    {'status': 'failed', 'pageRefs': []}, {'state': 'failed', 'pageRefs': []},
    {'state': 'not_executed', 'executed': False}, {'status': 'cancelled'},
    {'state': 'invalid_reference', 'message': '工作记录尚未读取或已被员工更新，请重新读取并核对后提出建议。'},
    {'state': 'not_found', 'members': {'items': [], 'total': 0}, 'message': '未找到该员工。'},
])
def test_shared_result_failure_does_not_turn_into_progress_or_read_evidence(result):
    context, job = state()
    receipt = record(context, job, 'read_work_material', 'failed', result, {'view': 'pages'})
    row = flow.current(context, job)['calls'][receipt]
    assert failed_result(result) and row['outcome'] == 'failed'
    assert outcome(ToolMessage(tool_call_id='failed', content=json.dumps(result)))[0] == 'failed'
    assert not flow.supported(row, 'fact', context, job)
    assert not reusable_read({'name': 'find_documents'}, result)
    assert result_key({'name': 'read_work_material', 'args': {}}, {**result, 'message': 'first'}) == result_key(
        {'name': 'read_work_material', 'args': {}}, {**result, 'message': 'different wording'})


@pytest.mark.parametrize('tool,args,result', [
    ('read_work_material', {}, {'kind': 'image', 'attachmentId': 'image', 'text': '交付日期11月6日', 'complete': True, 'status': 'ready'}),
    ('read_work_material', {}, {'kind': 'audio', 'attachmentId': 'audio', 'text': '下周五交付', 'nextCursor': None, 'status': 'ready'}),
    ('read_images', {'attachment_ids': ['image']}, {'state': 'succeeded', 'images': [{'id': 'image', 'complete': False}], 'text': '首行预算12800'}),
    ('read_images', {'attachment_ids': ['image']}, {'state': 'succeeded', 'images': [{'id': 'image', 'complete': True}], 'text': '首行预算12800'}),
    ('inspect_table', {'source': {'input_ref': {'attachment_id': 'table'}}}, {'state': 'succeeded', 'tool': 'inspect_table', 'data': {'rows': 200, 'sample': [[1]], 'truncated': True}}),
])
def test_real_media_and_tabular_facts_are_usable_without_claiming_full_original(tool, args, result):
    context, job = state()
    receipt = record(context, job, tool, 'read', result, args)
    row = flow.current(context, job)['calls'][receipt]
    assert flow.supported(row, 'fact', context, job)
    assert not flow.supported(row, 'full', context, job)


@pytest.mark.parametrize('name,read,result', [
    ('save_deliverable', 'read_deliverable', {'state': 'conflict', 'message': '成果已更新，请读取最新版本后修改'}),
    ('execute_business_action', 'get_work_item', {'state': 'conflict', 'message': '请先读取目标的最新版本，再决定修改'}),
])
def test_state_only_tool_failures_allow_failure_bound_refresh_before_retry(name, read, result):
    context, job = state()
    receipt = record(context, job, 'get_work_item', 'initial', {'id': 'work', 'revision': 1})
    tool, batch = call(name, 'attempt')
    assert flow.begin(context, job, tool, batch, {'ready': [receipt]}) is None
    failed = flow.identity(batch, tool)
    flow.end(context, job, {**tool, 'decisionId': failed}, ToolMessage(
        name=name, tool_call_id=tool['id'], content=json.dumps(result)))
    row = flow.current(context, job)['calls'][failed]
    assert row['outcome'] == 'failed' and row['recovery']
    refresh, refresh_batch = call(read, 'refresh')
    assert flow.begin(context, job, refresh, refresh_batch, {'after': failed, 'need': '读取当前版本'}) is None
    flow.end(context, job, {**refresh, 'decisionId': flow.identity(refresh_batch, refresh)}, ToolMessage(
        name=read, tool_call_id='refresh', content=json.dumps({'id': 'work', 'revision': 2})))
    retry, retry_batch = call(name, 'retry')
    assert flow.begin(context, job, retry, retry_batch, {}) is None
    extra, extra_batch = call(read, 'extra')
    assert flow.begin(context, job, extra, extra_batch, {'after': failed, 'need': '再次检查'}) is not None


@pytest.mark.parametrize('result', [
    {'state': 'failed', 'category': 'permission_denied'},
    {'state': 'invalid_reference', 'category': 'permission_denied'},
    {'state': 'clarification', 'category': 'missing_info'},
    {'state': 'unavailable', 'errorCode': 'http_403'},
    {'state': 'cancelled'}, {'state': 'interrupted'}, {'state': 'unknown'},
    {'state': 'not_requested'}, {'state': 'not_executed'},
])
def test_denied_or_terminal_results_do_not_reopen_closed_exploration(result):
    context, job = state()
    receipt = record(context, job, 'get_work_item', 'initial', {'id': 'work', 'revision': 1})
    assert ready(context, job, [receipt]) is None
    tool, batch = call('save_deliverable', 'save')
    failed = flow.identity(batch, tool)
    flow.end(context, job, {**tool, 'decisionId': failed}, ToolMessage(
        name=tool['name'], tool_call_id=tool['id'], content=json.dumps(result)))
    assert not flow.current(context, job)['calls'][failed]['recovery']
    read, read_batch = call('read_deliverable', 'refresh')
    assert flow.begin(context, job, read, read_batch, {'after': failed, 'need': '重新读取'}) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('name,who', [('propose_progress', 'employee'), ('propose_followup', 'admin')])
async def test_real_suggestion_reference_results_distinguish_stale_source_from_access_denial(setup, name, who):
    from app.agent.tools.business.work import propose_progress
    from app.agent.tools.business.team import propose_followup
    from _support.agent.business_actions import create, runtime
    work = await create(setup[3][who])
    foreign = await create(setup[3]['peer'])
    context, _ = await runtime(setup, '更新这项工作的进展', who)
    function = {'propose_progress': propose_progress, 'propose_followup': propose_followup}[name]
    args = {'title': '报价方案', 'summary': '等待确认', 'status': 'blocked', 'blocker': '待确认',
            'next_step': '确认后继续', 'runtime': SimpleNamespace(context=context)}
    if name == 'propose_followup':
        args['source_tokens'] = []
    stale = json.loads(await function.coroutine(**args, work_id=work['id']))
    denied = json.loads(await function.coroutine(**args, work_id=foreign['id']))
    assert stale['state'] == denied['state'] == 'invalid_reference'
    assert failed_result(stale) and failed_result(denied)
    assert stale['category'] == 'conflict' and recoverable_result(stale)
    assert denied['category'] == 'permission_denied' and not recoverable_result(denied)
    assert not context.intent_model.inputs


@pytest.mark.asyncio
async def test_actual_deliverable_conflict_can_refresh_then_save(setup):
    from app.agent.tools.resources.deliverables import read_deliverable, save_deliverable
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup, '保存并修改一份私人方案')
    invoke = SimpleNamespace(context=context)
    first = json.loads(await save_deliverable.coroutine('方案', '原文', invoke))
    conflict = json.loads(await save_deliverable.coroutine('方案', '补充后的正文', invoke,
        deliverable_id=first['id'], expected_revision=0, step=2))
    assert conflict['state'] == conflict['category'] == 'conflict'
    assert conflict['httpStatus'] == 409
    assert failed_result(conflict) and recoverable_result(conflict)
    latest = json.loads(await read_deliverable.coroutine(invoke, deliverable_id=first['id']))
    saved = json.loads(await save_deliverable.coroutine('方案', '补充后的正文', invoke,
        deliverable_id=latest['id'], expected_revision=latest['revision'], step=2))
    assert saved['state'] == 'succeeded' and saved['revision'] == latest['revision'] + 1
    assert saved['body'] == '补充后的正文'


@pytest.mark.asyncio
async def test_actual_context_quote_rejection_remains_denied_not_a_recovery_instruction(setup):
    from app.agent.tools.control.task_context import set_task_context
    from app.modules.conversations.task.task_schemas import TaskInterpretation
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup, '仅分析我的工作')
    result = json.loads(await set_task_context.coroutine(
        TaskInterpretation(directiveChange='replace', directiveQuote='以后都保存进展', directiveScope='自动保存'),
        SimpleNamespace(context=context)))
    assert result['state'] == 'invalid_reference' and result['category'] == 'permission_denied'
    assert failed_result(result) and not recoverable_result(result)


@pytest.mark.parametrize('kind,tool,argument,result', [
    ('work', 'get_work_item', 'work_id', {'id': 'B', 'revision': 2}),
    ('documents', 'read_document', 'attachment_id', {'attachment': {'id': 'B', 'extraction': {'revision': 2}},
        'sourceComplete': True, 'readScope': {'allExtractedTextReturned': True}}),
    ('deliverables', 'read_deliverable', 'deliverable_id', {'id': 'B', 'revision': 2, 'body': '保留正文'}),
])
def test_receipt_versions_are_source_local_and_survive_resume(kind, tool, argument, result):
    context, job = state()
    versions = flow.source_versions(context)[kind]
    versions.update(A=1, B=2)
    receipt = record(context, job, tool, 'B', result, {argument: 'B'})
    job.result = json.loads(json.dumps(job.result))
    row = flow.current(context, job)['calls'][receipt]
    assert row['sources'][kind] == {'B': 2}
    versions['A'] = 3
    assert flow.supported(row, 'fact', context, job)
    versions['B'] = 3
    assert not flow.supported(row, 'fact', context, job)


def test_returned_revision_cannot_be_upgraded_by_another_parallel_read():
    context, job = state()
    context.document_versions.update(A=3, B=2)
    receipt = record(context, job, 'read_document', 'old-result', {'attachment': {'id': 'A', 'extraction': {'revision': 2}},
        'sourceComplete': True, 'readScope': {'allExtractedTextReturned': True}}, {'attachment_id': 'A'})
    row = flow.current(context, job)['calls'][receipt]
    assert row['sources']['documents'] == {'A': 2}
    assert not flow.supported(row, 'fact', context, job)


def test_material_receipt_binds_actual_work_and_attachment_without_scanning_prose():
    context, job = state()
    context.read_versions.update(work=3, unrelated_work=8)
    context.document_versions.update(audio=2, unrelated=4)
    receipt = record(context, job, 'read_work_material', 'audio', {
        'attachmentId': 'audio', 'kind': 'audio', 'text': 'unrelated unrelated_work', 'status': 'ready'},
        {'work_id': 'work', 'material_id': 'material'})
    row = flow.current(context, job)['calls'][receipt]
    assert row['sources']['work'] == {'work': 3}
    assert row['sources']['documents'] == {'audio': 2}


def test_image_source_revision_is_bound_from_actual_existing_receipt():
    context, job = state()
    job.result['sandboxSources'] = [{'kind': 'attachment', 'id': 'image', 'revision': 1, 'sha256': 'bytes'},
        {'kind': 'attachment', 'id': 'other', 'revision': 1, 'sha256': 'other-bytes'}]
    receipt = record(context, job, 'read_images', 'pixels', {
        'state': 'succeeded', 'images': [{'id': 'image', 'complete': True}], 'text': '真实图片文字'}, {'attachment_ids': ['image']})
    job.result = json.loads(json.dumps(job.result))
    row = flow.current(context, job)['calls'][receipt]
    assert set(row['sources']['attachments']) == {'image'}
    job.result['sandboxSources'][1]['revision'] = 2
    assert flow.supported(row, 'fact', context, job)
    job.result['sandboxSources'][0]['revision'] = 2
    assert not flow.supported(row, 'fact', context, job)


def test_execution_recovery_can_locate_then_read_multiple_pages_before_retry():
    context, job = state()
    evidence = record(context, job, 'get_work_item', 'initial', {'id': 'work', 'revision': 1})
    tool, batch = call('run_python', 'run')
    assert flow.begin(context, job, tool, batch, {'ready': [evidence]}) is None
    failed = flow.identity(batch, tool)
    flow.end(context, job, {**tool, 'decisionId': failed}, ToolMessage(name='run_python', tool_call_id='run',
        content=json.dumps({'state': 'failed', 'category': 'invalid_arguments', 'recovery': {'owner': 'assistant', 'nextAction': 'repair'}, 'executionId': 'execution', 'exitCode': 1, 'stderr': 'missing column'})))
    for identifier, name, args, result in [
        ('locate', 'find_documents', {}, {'items': [{'id': 'table'}], 'nextCursor': None}),
        ('header', 'read_document', {'attachment_id': 'table', 'start': 0}, {'readScope': {'allExtractedTextReturned': False}, 'items': [{'text': '部门、金额'}], 'nextCursor': 40}),
        ('remaining', 'read_document', {'attachment_id': 'table', 'start': 40}, {'readScope': {'allExtractedTextReturned': False}, 'items': [{'text': '研发18500'}], 'nextCursor': None}),
    ]:
        current, current_batch = call(name, identifier, args)
        assert flow.begin(context, job, current, current_batch, {'after': failed, 'need': '取得缺少的部门金额列'}) is None
        flow.end(context, job, {**current, 'decisionId': flow.identity(current_batch, current)}, ToolMessage(
            name=name, tool_call_id=identifier, content=json.dumps(result)))
        assert flow.current(context, job)['phase'] == 'recovering'
        assert 'read_document' in flow.available(flow.current(context, job), {'read_document', 'run_python'})
    unrelated, unrelated_batch = call('web_search', 'unrelated')
    assert flow.begin(context, job, unrelated, unrelated_batch, {'need': '顺便查背景'}) is not None
    retry, retry_batch = call('run_python', 'retry')
    assert flow.begin(context, job, retry, retry_batch, {}) is None
    assert flow.current(context, job)['phase'] == 'executing'
    extra, extra_batch = call('read_document', 'extra', {'attachment_id': 'table'})
    assert flow.begin(context, job, extra, extra_batch, {'after': failed, 'need': '再确认'}) is not None


@pytest.mark.parametrize('phase', ['exploring', 'executing'])
def test_required_work_refresh_preserves_the_original_decision(phase):
    context, job = state()
    context.refresh_work_versions['work'] = 1
    value = flow.current(context, job)
    value['phase'] = phase
    flow.save(job, value)
    record(context, job, 'get_work_item', 'refresh', {'id': 'work', 'revision': 2}, {'work_id': 'work'})
    assert flow.current(context, job)['phase'] == phase


def test_registered_tool_contract_inventory_covers_all_result_families():
    from app.agent.prompts.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES
    examples = {
        'load_tools': ({}, {'state': 'loaded'}, 'control'),
        'request_user_input': ({}, {'state': 'waiting', 'interactionId': 'q'}, 'control'),
        'set_task_context': ({}, {'state': 'updated'}, 'control'),
        'finish_task': ({}, {'answer': 'done'}, 'control'),
        'read_file': ({}, {'text': 'stored virtual summary'}, 'reference'),
        'get_business_actions': ({}, {'value': [{'state': 'running'}]}, 'directory'),
        'read_execution': ({'execution_id': 'e'}, {'evidenceType': 'execution_receipt', 'state': 'succeeded', 'stdout': 'sum=10'}, 'receipt'),
        'find_documents': ({}, {'items': [{'id': 'doc'}]}, 'directory'),
        'list_work_materials': ({'work_id': 'w'}, {'workId': 'w', 'items': []}, 'directory'),
        'read_document': ({'attachment_id': 'd'}, {'readScope': {'allExtractedTextReturned': False}, 'items': [{'text': 'excerpt'}]}, 'text'),
        'read_work_material': ({'work_id': 'w', 'material_id': 'm'}, {'kind': 'audio', 'attachmentId': 'a', 'text': 'transcript'}, 'text'),
        'read_images': ({'attachment_ids': ['i']}, {'state': 'succeeded', 'images': [{'id': 'i', 'complete': True}], 'text': 'observed'}, 'text'),
        'inspect_table': ({'source': {'input_ref': {'attachment_id': 't'}}}, {'state': 'succeeded', 'data': {'rows': 10, 'sample': []}}, 'records'),
        'web_search': ({'query': 'official docs'}, {'items': [{'url': 'https://example.org', 'snippet': 'docs'}]}, 'link'),
        'web_fetch': ({'url': 'https://example.org'}, {'evidenceType': 'page_text', 'text': 'excerpt', 'truncated': True}, 'text'),
    }
    for name in flow.RECORD_READS:
        examples[name] = ({'deliverable_id': 'd'} if name == 'read_deliverable' else {},
                          {'items': [{'id': 'record', 'content': {'text': 'actual record'}}]}, 'records')
    for name in flow.EXECUTION - {'finish_task', 'set_task_context'}:
        examples[name] = ({}, {'state': 'succeeded', 'id': 'actual-receipt'}, 'receipt')
    assert set(examples) == ALLOWED_TOOLS | TEAM_TOOL_NAMES | {'load_tools'}
    for name, (args, result, kind) in examples.items():
        tool, _ = call(name, name, args)
        message = ToolMessage(name=name, tool_call_id=name, content=json.dumps(result))
        assert flow.facts(tool, result, message)['kind'] == kind, name
    # Unknown or malformed adapter shapes do not become evidence merely because
    # their name starts with read/get/query or they returned HTTP success.
    for name in ('read_document', 'get_work_item', 'inspect_table', 'new_read_tool'):
        tool, _ = call(name, 'unknown')
        row = flow.facts(tool, {'unexpected': 'shape'}, ToolMessage(tool_call_id='unknown', content='{}'))
        assert row['kind'] == 'unknown'


def test_checkpoint_scope_and_optional_envelope_do_not_become_authorization():
    context, job = state()
    receipt = record(context, job, 'web_search', 'links', {'items': [{'url': 'https://example.org'}]})
    assert ready(context, job, [receipt], 'link') is None
    assert flow.current(replace(context, fence=2), job)['phase'] == 'executing'
    for changed in (replace(context, owner_id='other'), replace(context, company_id='other'),
                    replace(context, job_id='other'), replace(context, source_revision=1),
                    replace(context, document_snapshot='changed'), replace(context, node_scope='changed')):
        assert flow.current(changed, job)['phase'] == 'exploring'
    tool, _ = call('read_document', 'legacy', {'attachment_id': 'actual', '_flow': {'ready': 'invalid'}})
    cleaned, control = flow.clean(tool)
    assert cleaned['args'] == {'attachment_id': 'actual'} and not control
    assert not context.document_versions and not context.read_versions
    original = read_document.tool_call_schema.model_json_schema()
    decorated = flow.schemas([read_document])[0]['function']['parameters']
    assert decorated['properties']['_flow'] == {'type': 'object'}
    assert read_document.tool_call_schema.model_json_schema() == original
    assert '_flow' not in decorated['required']


@pytest.mark.parametrize('value', [
    None, [], 'ready', {'unknown': True}, {'need': 'x' * 161}, {'need': []},
    {'after': 'x' * 81}, {'after': 1}, {'ready': 'receipt'}, {'ready': ['receipt'] * 17},
    {'ready': ['x' * 81]}, {'ready': [1]}, {'scope': 'everything'}, {'independent': 'true'},
])
def test_compact_optional_schema_keeps_strict_envelope_validation_and_legacy_arguments(value):
    tool, _ = call('read_document', 'optional', {'attachment_id': 'actual', '_flow': value})
    cleaned, control = flow.clean(tool)
    assert cleaned['args'] == {'attachment_id': 'actual'} and control == {}


def test_compact_optional_schema_accepts_only_existing_protocol_fields():
    value = {'need': '读取当前版本', 'after': 'failed-receipt', 'ready': ['fact-receipt'],
             'scope': 'fact', 'independent': True}
    tool, _ = call('save_deliverable', 'optional', {'title': '方案', '_flow': value})
    cleaned, control = flow.clean(tool)
    assert cleaned['args'] == {'title': '方案'} and control == value


def test_first_tool_schema_requires_short_decision_but_legacy_calls_stay_safe():
    from app.agent.tools.control.questions import request_user_input
    schemas = flow.schemas([read_document, request_user_input], first=True)
    parameters = schemas[0]['function']['parameters']
    assert '_flow' in parameters['required']
    assert parameters['properties']['_flow'] == {'type': 'object', 'required': ['route', 'need']}
    assert '_flow' not in schemas[1]['function']['parameters']['properties']
    # The wire field names are explicit; runtime owns enum/size validation.
    for metadata, expected in [({}, 'unknown'), ({'route': 'fact', 'need': '查预算'}, 'fact'),
                               ({'route': 'execute', 'need': '保存明确方案'}, 'execute'),
                               ({'route': 'execute'}, 'unknown'),
                               ({'route': 'fact', 'need': '   '}, 'unknown'),
                               ({'route': 'authorized', 'need': '自报权限'}, 'unknown')]:
        context, job = state()
        original, batch = call('read_document', expected, {'attachment_id': 'actual', '_flow': metadata})
        cleaned, control = flow.clean(original)
        assert cleaned['args'] == {'attachment_id': 'actual'}
        assert flow.begin(context, job, cleaned, batch, control) is None
        row = flow.current(context, job)['calls'][flow.identity(batch, cleaned)]
        assert row['route'] == expected
        assert flow.current(context, job)['phase'] == 'exploring'
        assert '_flow' not in flow.schemas([read_document])[0]['function']['parameters']['required']


def test_fact_route_cannot_close_exploration_and_mixed_batch_keeps_individual_routes():
    context, job = state()
    receipt = record(context, job, 'get_work_item', 'read', {'id': 'work', 'revision': 1})
    read, _ = call('read_document', 'fact')
    write, _ = call('save_deliverable', 'execute')
    batch = AIMessage(id='mixed-routes', content='', tool_calls=[read, write])
    assert flow.begin(context, job, write, batch, {'route': 'execute', 'need': '保存方案'}) is None
    assert flow.begin(context, job, read, batch, {'route': 'fact', 'need': '仍需预算', 'ready': [receipt]}) is None
    saved = flow.current(context, job)
    assert saved['phase'] == 'exploring'
    assert saved['calls'][flow.identity(batch, read)]['route'] == 'fact'
    assert saved['calls'][flow.identity(batch, write)]['route'] == 'execute'


@pytest.mark.parametrize('order', [('find_work_items', 'request_user_input'), ('request_user_input', 'find_work_items')])
def test_question_batch_decision_is_order_independent(order):
    context, job = state()
    calls = [{'name': name, 'id': name, 'args': {}} for name in order]
    batch = AIMessage(id='shared-batch', content='', tool_calls=calls)
    for tool in calls:
        result = flow.begin(context, job, tool, batch, {})
        assert (result is None) == (tool['name'] == 'request_user_input')
    assert flow.current(context, job)['pending'] == ['find_work_items']


@pytest.mark.parametrize('question_first', [True, False])
def test_independence_is_batch_local_and_cannot_override_dependencies(question_first):
    context, job = state()
    question, _ = call('request_user_input', 'question')
    read, _ = call('find_work_items', 'independent')
    batch = AIMessage(id='original', content='', tool_calls=[question, read])
    if question_first:
        flow.begin(context, job, question, batch, {})
        flow.end(context, job, {**question, 'decisionId': flow.identity(batch, question)}, ToolMessage(
            name=question['name'], tool_call_id=question['id'], content=json.dumps({'state': 'waiting', 'interactionId': 'real-question'})))
    assert flow.begin(context, job, read, batch, {'independent': True}) is None
    if not question_first:
        flow.begin(context, job, question, batch, {})
        flow.end(context, job, {**question, 'decisionId': flow.identity(batch, question)}, ToolMessage(
            name=question['name'], tool_call_id=question['id'], content=json.dumps({'state': 'waiting', 'interactionId': 'real-question'})))
    followup, followup_batch = call('find_work_items', 'later')
    assert flow.begin(context, job, followup, followup_batch, {'independent': True}) is not None
    dependent, _ = call('execute_business_action', 'dependent', {'requires_step': 1})
    dependent_batch = AIMessage(id='other', content='', tool_calls=[question, dependent])
    assert flow.begin(context, job, dependent, dependent_batch, {'independent': True}) is not None
    assert flow.current(context, job)['phase'] == 'waiting'


class QuestionFirstModel(ReviewedFixtureModel):
    calls: int = 0
    independent: bool = False
    async def _agenerate(self, messages, **kwargs):
        self.calls += 1
        assert self.calls == 1, 'Waiting must not call the model again'
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[
            {'id': 'unused-read', 'name': 'find_work_items', 'args': {'query': ''}},
            {'id': 'ask', 'name': 'request_user_input', 'args': {'questions': [
                {'id': 'meaning', 'type': 'text', 'prompt': '你要保存原文件，还是整理后的文字？'}]}},
            {'id': 'unused-write', 'name': 'execute_business_action', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '不得猜测'},
                **({'_flow': {'independent': True}} if self.independent else {})}},
        ]))])


@pytest.mark.asyncio
async def test_real_graph_first_question_prevents_parallel_reads_and_writes(setup):
    model = QuestionFirstModel(model='controlled-flow', api_key='no-network')
    result, stored = await run(setup, model, '把之前的加到我的工作里')
    assert model.calls == 1 and result['job']['taskOutcome']['state'] == 'needs_input'
    assert not result['actions'] and not stored.get('ownWorkSearched')
    assert stored['decisionFlow']['phase'] == 'waiting'
    assert set(stored['decisionFlow']['pending']) == {'find_work_items', 'execute_business_action'}
    refreshed = (await setup[3]['employee'].get('/api/v1/messages/' + result['id'])).json()
    assert refreshed['interactions'][0]['questions'][0]['prompt'] == '你要保存原文件，还是整理后的文字？'


@pytest.mark.asyncio
async def test_real_graph_independent_operation_keeps_authorization_receipt_and_question(setup):
    model = QuestionFirstModel(model='controlled-flow', api_key='no-network', independent=True)
    result, stored = await run(setup, model, '把之前的加到我的工作里；另外单独新建一个标题为“不得猜测”的工作，其他字段留空。')
    assert model.calls == 1 and result['job']['state'] == 'awaiting_input'
    assert result['job']['taskOutcome']['state'] == 'partial' and result['job']['taskOutcome']['nextAction'] == 'reply'
    assert len(result['actions']) == 1 and result['actions'][0]['state'] == 'succeeded'
    assert stored['decisionFlow']['phase'] == 'waiting'
    assert stored['decisionFlow']['pending'] == ['find_work_items']
    assert result['interactions'][0]['state'] == 'waiting'
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert len(works) == 1 and works[0]['title'] == '不得猜测'


@pytest.mark.asyncio
async def test_ordinary_answer_keeps_single_original_model_call(setup):
    model = DeliveryModel(model='controlled-flow', api_key='no-network', raw_first=True, answer='可以先列出今天最重要的一件事。')
    result, stored = await run(setup, model, '今天有些忙，给个简短建议')
    assert model.calls == 1 and result['reply'] == model.answer
    assert stored['decisionFlow']['phase'] == 'delivering' and not stored['decisionFlow']['calls']
    assert not stored.get('deliveryRepairs')
