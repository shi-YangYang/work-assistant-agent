"""Fixed fault branches exercise actual authorization, persistence and public DTOs."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import func, select

from app.agent.actions.intent import IntentVerdict, recovery_contract
from app.agent.actions.operations import execute
from app.agent.actions.task_outcomes import barrier, blocked
from app.agent.actions.work_change_plan import source_input
from app.agent.runtime.tool_nodes import outcome
from app.tasks.feedback.outcomes import derive
from app.tasks.feedback.public import prose, model_result
from app.tasks.models import Job
from app.tasks.serializers import job_dto
from app.modules.operations.models import BusinessAction
from _support.agent.business_actions import create, read_work
from _support.agent.execution_permissions import mode_runtime
from _support.work.work_change_plan import PlanJudge

pytestmark = pytest.mark.asyncio


def request():
    return {'currentUserText': '之前的都添加到我的工作里面',
            'conversationTask': {'workReference': {'id': 'selected', 'revision': 2},
                                 'interactionAnswers': [{'text': '放到资料整理'}],
                                 'previousTask': {'remaining': ['materials 未要求修改'], 'userSources': []}},
            'verifiedReads': {'ownWorkRead': [{'id': 'selected'}]},
            'privateDeliverables': {'items': [{'id': 'file-a'}, {'id': 'file-b'}]},
            'conversationForReferenceOnly': [], 'messageTime': '2026-10-20T12:00:00+08:00',
            'timezone': 'Asia/Shanghai'}


async def test_scope_input_keeps_user_target_and_answers_but_not_old_refusal():
    value = source_input(request(), {'action': 'update_work', 'targetId': 'selected',
                                    'expectedRevision': 2}, 'current')
    assert value['conversationTask']['workReference'] == {'id': 'selected', 'revision': 2}
    assert value['conversationTask']['interactionAnswers'] == [{'text': '放到资料整理'}]
    assert 'remaining' not in value['conversationTask']['previousTask']
    assert value['privateDeliverables']['items'] == request()['privateDeliverables']['items']


@pytest.mark.parametrize('owner,missing', [
    ('assistant', [{'field': 'target', 'question': '保存到哪里？', 'unavailableFromSources': '没有位置'}]),
    ('user', []),
    ('user', [{'field': 'target', 'question': '保存到哪里？', 'unavailableFromSources': '没有位置',
               'candidateIds': ['invented-id']}]),
])
async def test_incoherent_missing_info_never_becomes_user_question_or_authorization(owner, missing):
    value = IntentVerdict(allowed=False, quote='之前的都添加到我的工作里面',
                          reason='助手可自行修正的内部前置问题', failureKind='missing_info',
                          recoveryOwner=owner, missingInputs=missing)
    checked = recovery_contract(value, request())
    assert not checked.allowed and checked.failureKind == 'invalid_arguments'
    assert checked.recoveryOwner == 'assistant' and not checked.missingInputs


async def test_real_user_gap_is_narrow_and_model_receives_no_judge_diagnostic(setup):
    context, _ = await mode_runtime(setup, 'full', '新建一项工作，但先让我选择保存位置')

    class GapJudge:
        async def ainvoke(self, messages):
            value = json.loads(messages[-1].content)
            return AIMessage(content=json.dumps({
                'allowed': False, 'quote': value['currentUserText'],
                'reason': '服务端没放行：denialScope=target',
                'failureKind': 'missing_info', 'denialScope': 'target', 'recoveryOwner': 'user',
                'missingInputs': [{'field': 'target', 'question': '要新建工作，还是加入已有工作？',
                                   'unavailableFromSources': '用户要求先选择位置', 'candidateIds': []}],
            }))

    context.intent_model = GapJudge()
    result = await execute(context, step=1, action='create_work', changes={'title': '资料整理'})
    assert result['state'] == 'waiting'
    rendered = model_result(result)
    assert rendered['message'] == '请补充下面的信息，我会继续原任务。'
    assert rendered['interactionId']
    assert 'diagnostic' not in rendered
    assert '没放行' not in json.dumps(rendered, ensure_ascii=False)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state = 'awaiting_input'
        job.result = {**job.result, 'taskOutcome': derive(job)}
        public = job_dto(job)
        assert public['taskOutcome']['nextAction'] == 'reply'
        assert public['operationFeedback'][0]['message'] == rendered['message']
        assert 'denialScope' not in json.dumps(public, ensure_ascii=False)
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(
            BusinessAction.message_id == job.target_id)) == 0


async def test_preserved_field_repair_is_bounded_but_removing_extra_field_can_succeed(setup):
    work = await create(setup[3]['employee'], '资料整理')
    context, _ = await mode_runtime(setup, 'full', '只把这项工作标为已完成')
    await read_work(context, work['id'])
    plan = PlanJudge({'status': ('set', '标为已完成', 'done')})
    context.work_change_model = plan
    from _support.agent.assistant_execution import ReceiptJudge
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '标为已完成', 'field': 'status', 'kind': 'status'}])
    bad = dict(action='update_work', target_id=work['id'], expected_revision=1,
               changes={'status': 'done', 'nextStep': '擅自添加'})
    first = await execute(context, step=1, **bad)
    assert first['state'] == 'failed' and first['recovery']['nextAction'] == 'stop'
    second = await execute(context, step=2, **{**bad, 'changes': {'status': 'done', 'nextStep': '换一种说法'}})
    assert second['state'] == 'failed' and len(plan.inputs) == 2
    result = await execute(context, step=1, **{**bad, 'changes': {'status': 'done'}})
    assert result['state'] == 'succeeded'
    after = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['status'] == 'done' and after['nextStep'] == ''


async def test_target_question_cannot_be_evaded_by_new_work_but_new_evidence_rechecks(setup):
    context, _ = await mode_runtime(setup, 'full', '之前的都添加到我的工作里面')
    proposal = {'action': 'update_work', 'targetId': 'old', 'requestStep': 1,
                'taskItemId': 'checked-item',
                'changes': {'materials': [{'deliverableId': 'file', 'revision': 1, 'fileId': 'stable-file'}]}}
    recovery = {'owner': 'user', 'nextAction': 'ask', 'missingInputs': [
        {'field': 'target', 'question': '放到哪项工作？', 'unavailableFromSources': '没有指定位置'}]}
    await barrier(context, proposal, 'target choice', evidence='same-facts', kind='missing_info', recovery=recovery)
    changed = {**proposal, 'action': 'create_work', 'targetId': '', 'requestStep': 7}
    assert (await blocked(context, changed, 'same-facts'))['category'] == 'missing_info'
    assert await blocked(context, changed, 'user-selected-target') is None
    other = {**proposal, 'targetId': 'another-work', 'taskItemId': 'another-checked-item'}
    assert await blocked(context, other, 'same-facts') is None
    # Same files do not prove the same intent when the main agent omits item IDs.
    independent = {key: value for key, value in other.items() if key != 'taskItemId'}
    assert await blocked(context, independent, 'same-facts') is None
    from app.core.digests import digest
    omitted = {key: value for key, value in changed.items() if key != 'taskItemId'}
    context.task_item_keys[digest(omitted)] = 'checked-item'
    assert await blocked(context, omitted, 'same-facts')


async def test_failure_prose_stream_and_final_share_projection_without_censoring_technical_questions():
    job = SimpleNamespace(result={'toolOutcomes': [{
        'category': 'invalid_arguments', 'message': '变更计划不匹配：materials 未要求修改',
        'diagnostic': '变更计划不匹配：materials 未要求修改',
        'fieldIssues': [{'field': 'materials', 'code': 'not_requested'}],
    }]})
    raw = '已保存第一项。\n服务端这次还是没放行，materials 未要求修改。\n第二项暂未保存。'
    visible = ''
    for index in range(1, len(raw) + 1):
        current = prose(raw[:index], job, '保存这两项', complete=False)
        assert current.startswith(visible)
        assert 'materials' not in current and '没放行' not in current
        visible = current
    final = prose(raw, job, '保存这两项')
    assert final.startswith(visible) and '已保存第一项' in final and '第二项暂未保存' in final
    technical = '代码中的 materials 是材料数组，missing_info 表示缺少信息。'
    assert prose(technical, job, '解释代码中的 materials 和 missing_info') == technical
    assert prose(technical, job, '解释这个附件里的代码') == technical
    assert prose('materials 是附件数组，body 是正文。', job, '分析文件') == 'materials 是附件数组，body 是正文。'
    assert prose('普通答案持续流式输出', SimpleNamespace(result={}), '普通问题', complete=False) == '普通答案持续流式输出'


async def test_existing_user_target_cannot_be_called_a_missing_selection():
    payload = {**request(), 'proposedOperation': {'targetId': 'selected'}}
    verdict = IntentVerdict(allowed=False, quote='保存到这项工作', reason='没有保存位置',
        failureKind='missing_info', recoveryOwner='user', missingInputs=[
            {'field': 'target', 'question': '保存到哪里？', 'unavailableFromSources': '目标不明'}])
    checked = recovery_contract(verdict, payload)
    assert not checked.allowed and checked.failureKind == 'invalid_arguments'
    assert not checked.missingInputs


async def test_public_node_and_historical_context_remove_diagnostics_without_rewriting_history(setup):
    from app.modules.messages.models import Message
    from app.modules.conversations.references import message_reference
    from app.tasks.nodes.node_state import node_dtos
    context, _ = await mode_runtime(setup, 'full', '把文件保存到我的工作')
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        message = await db.get(Message, job.target_id)
        message.reply = '服务端没放行：变更计划不匹配，materials 未要求修改。请告诉我要存到哪项工作？'
        job.result = {**job.result, 'toolOutcomes': [{
            'category': 'invalid_arguments', 'message': '变更计划不匹配：materials 未要求修改'}],
            'nodeExecution': {'scope': 'test', 'nodes': [{
                'id': 'failed', 'scope': 'test', 'kind': 'tool', 'label': '保存材料',
                'state': 'failed', 'attempts': 1, 'error': '变更计划不匹配：materials 未要求修改',
            }]}}
        reference = await message_reference(db, setup[2]['employee'], message, job=job, job_loaded=True)
        assert 'materials' not in reference['assistantReference']
        assert reference['assistantReference'] == ''  # Old refused proposals/questions are not current intent.
        assert reference['userText'] == '把文件保存到我的工作'
        assert '变更计划' not in node_dtos(job)[0]['error']
        assert 'materials' in message.reply  # Original historical record stays intact.


async def test_uncategorized_legacy_failure_does_not_tell_user_to_supply_more_information():
    job = SimpleNamespace(state='awaiting_input', phase='complete', error='', result={
        'toolOutcomes': [{'category': 'missing_info', 'message': '变更计划不匹配', 'label': '更新工作'}],
        'taskInterpretation': {'state': 'needs_input', 'remaining': []}})
    result = derive(job)
    assert result['state'] == 'blocked' and result['nextAction'] == 'none'
    for value in ({'state': 'waiting', 'message': '前置工具尚未成功'},
                  {'state': 'clarification', 'category': 'invalid_arguments'}):
        assert outcome(ToolMessage(content=json.dumps(value), name='execute_business_action', tool_call_id='x'))[0] == 'failed'


@pytest.mark.parametrize('required,field,change', [
    (['body', 'bodyEdits'], 'body', {'bodyEdits': [{'action': 'append', 'blocks': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': '交付前核对来源'}]}]}]}),
    (['materials', 'materialIds'], 'materials', None),
])
async def test_authorization_aliases_cover_one_actual_write_not_two_required_fields(setup, required, field, change):
    from _support.agent.assistant_execution import ReceiptJudge
    from _support.materials.documents import upload
    from app.modules.attachments.models import Attachment
    from app.modules.messages.models import Message
    work = await create(setup[3]['employee'], '资料整理')
    text = '将这些材料保存到这项工作' if field == 'materials' else '补充正文：交付前核对来源'
    context, _ = await mode_runtime(setup, 'full', text)
    if change is None:
        attachment = await upload(setup[3]['employee'], 'facts.txt', b'checked material', 'text/plain')
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            message = await db.get(Message, job.target_id)
            row = await db.get(Attachment, attachment['id'])
            row.message_id = message.id
        change = {'materials': [{'attachmentId': attachment['id']}]}
    await read_work(context, work['id'])
    context.work_change_model = PlanJudge({field: ('set', text, None)})
    context.intent_model = ReceiptJudge(required_fields=required, requested_changes=[
        {'quote': text, 'field': required[-1], 'kind': 'material' if field == 'materials' else 'content'}])
    result = await execute(context, step=1, action='update_work', target_id=work['id'],
                           expected_revision=1, changes=change)
    assert result['state'] == 'succeeded', result
    assert len(context.intent_model.inputs) == 1
    repeated = await execute(context, step=1, action='update_work', target_id=work['id'],
                             expected_revision=1, changes=change)
    assert repeated['id'] == result['id']
    path = '/api/v1/work-items/' + work['id']
    detail = (await setup[3]['employee'].get(path)).json()
    if field == 'materials':
        materials = (await setup[3]['employee'].get(path + '/materials')).json()['items']
        assert len(materials) == 1
    else:
        assert '交付前核对来源' in json.dumps(detail['body'], ensure_ascii=False)


@pytest.mark.parametrize('canonical,alias', [('body', 'bodyEdits'), ('materials', 'materialIds')])
async def test_recovery_gap_compares_field_aliases_in_both_directions(canonical, alias):
    from app.agent.actions.task_outcomes import same_gap
    for field, supplied in ((canonical, alias), (alias, canonical)):
        proposal = {'changes': {supplied: ['same attempted change']}}
        assert same_gap({'fieldIssues': [{'field': field, 'code': 'not_requested'}]}, proposal)
        assert not same_gap({'fieldIssues': [{'field': field, 'code': 'missing'}]}, proposal)
        assert same_gap({'fieldIssues': [{'field': field, 'code': 'missing'}]}, {'changes': {}})


@pytest.mark.parametrize('kind,expected', [('invalid_arguments', 'assistant'), ('conflict', 'assistant'),
                                         ('permission_denied', 'system'), ('not_requested', 'none')])
async def test_non_user_failures_cannot_return_empty_user_ask(kind, expected):
    verdict = IntentVerdict(allowed=False, quote='保存', reason='请修正', failureKind=kind,
        recoveryOwner='user', missingInputs=[{'field': 'content', 'question': '补什么？',
                                             'unavailableFromSources': 'test'}])
    checked = recovery_contract(verdict, request())
    assert checked.recoveryOwner == expected and not checked.missingInputs


async def test_native_multi_sentence_repair_never_leaks_through_stream_or_remaining(setup):
    from app.agent.actions.operations import repair_failure
    from app.tasks.feedback.public import error, outcome as public_outcome
    diagnostic = '变更计划不匹配：materials 未要求修改，保留原值。请按原始要求修正 changes 再执行，本次未写入，不需要用户重复授权。'
    failure = repair_failure(diagnostic, code='field_scope_mismatch')
    job = SimpleNamespace(result={'toolOutcomes': [failure]})
    previous = ''
    for size in range(1, len(diagnostic) + 1):
        visible = prose(diagnostic[:size], job, '保存文件', complete=False)
        assert visible.startswith(previous)
        assert not any(word in visible for word in ('changes', 'materials', '重新授权', '原始要求'))
        previous = visible
    remaining = public_outcome({'reason': diagnostic, 'remaining': [diagnostic], 'nextAction': 'none'}, job)
    assert 'changes' not in json.dumps(remaining, ensure_ascii=False)
    assert error('Schema 校验失败，请修正 changes') == '这项操作暂未完成，已保存的内容会保留。'
    assert '系统判定' not in prose('系统判定没有明确要求保存这批文件，所以拦下了。', job, '全部保存')
    context, _ = await mode_runtime(setup, 'full', '生成今天的日报')
    failed = await execute(context, step=1, action='generate_report', changes={'completed': '不要由模型填入'})
    rendered = model_result(failed)
    assert rendered['recovery']['code'] == 'report_parameters'
    assert rendered['recovery']['owner'] == 'assistant'
    assert rendered['fieldIssues'] == [{'field': 'changes', 'code': 'not_supported'}]
    assert 'report_kind' not in rendered['message'] and 'diagnostic' not in rendered
