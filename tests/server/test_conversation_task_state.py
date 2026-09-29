"""Durable scope, provenance, continuation and outcome boundaries."""
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from app.agent.intent import authorize_intent
from app.agent.operations import execute
from app.agent.task_context import load, projection
from app.agent.tools.work import propose_progress
from app.modules.conversations.models import ConversationTaskState
from app.modules.conversations.task_state import finish as save_task, invalidate_sources
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.outcomes import derive
from app.tasks.lease import lease
from test_business_actions import create, finish, read_work, runtime
from test_company import keyed

pytestmark = pytest.mark.asyncio


class ScopedJudge:
    def __init__(self, *, source='', quote='', allowed=True, resume=False, append=(), append_values=None, kind='missing_info', interpretation=None, directive_target='', directive_fields=(), preview=False):
        self.source, self.quote, self.allowed, self.resume, self.append, self.kind = source, quote, allowed, resume, append, kind
        self.inputs = []
        self.interpretation = interpretation
        self.directive_target, self.directive_fields = directive_target, directive_fields
        self.append_values = append_values
        self.preview = preview

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        return AIMessage(content=json.dumps({'allowed': self.allowed, 'quote': self.quote or payload['currentUserText'],
            'quoteMessageId': self.source, 'reason': '' if self.allowed else '请说明要更新的对象',
            'requireConfirmation': self.preview, 'resumeTask': self.resume, 'appendFields': list(self.append),
            'appendValues': self.append_values if self.append_values is not None else {name: payload['proposedOperation']['changes'][name] for name in self.append},
            'failureKind': self.kind, 'taskContext': self.interpretation,
            'directiveTargetId': self.directive_target, 'directiveFields': list(self.directive_fields)}))


async def close_task(context, *, quote='', scope='', state='completed', goal='', relation='new', change=None):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await db.get(Message, job.target_id)
        await load(context, db, actor, job, message)
        value = {'goal': goal or message.text, 'state': state, 'relation': relation,
            'directiveChange': change or ('replace' if quote else 'keep'), 'directiveQuote': quote,
            'directiveScope': scope, 'remaining': ['需要一个明确对象'] if state == 'needs_input' else []}
        job.state = 'awaiting_input' if state == 'needs_input' else 'succeeded'
        job.result = {**job.result, 'taskInterpretation': value}
        from app.modules.operations.receipts import message_actions
        from app.modules.work.draft_receipts import message_drafts
        outcome = derive(job, await message_actions(db, actor, message), await message_drafts(db, actor, message, job), interpretation=value)
        await save_task(db, actor, job, message, value, outcome)
        job.lease_until = None


async def test_continuing_instruction_survives_new_worker_and_context_rebuild_and_appends(setup):
    _, sessions, users, clients = setup
    work = await create(clients['admin'], '上线web', summary='已有发布方案', nextStep='验收', blocker='等待审批')
    first, sent = await runtime(setup, '接下来我发的进展关联到上线web，只补充说明，保留其他字段', 'admin')
    quote = '接下来我发的进展关联到上线web，只补充说明，保留其他字段'
    await close_task(first, quote=quote, scope='上线web.summary 追加，其他字段不变')
    from app.modules.conversations.context_invalidation import invalidate
    async with sessions.begin() as db:
        await invalidate(db, owner_id=users['admin'].id)
    context, _ = await runtime(setup, '仓库 https://example.org/repo，今天有多次提交', 'admin')
    context.intent_model = ScopedJudge(source=sent['messageId'], quote=quote, append=['summary'])
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'summary': '仓库 https://example.org/repo，今天有多次提交'})
    assert result['state'] == 'succeeded'
    async with sessions() as db:
        saved = await db.get(WorkItem, work['id'])
        assert saved.content['summary'] == '已有发布方案\n仓库 https://example.org/repo，今天有多次提交'
        assert saved.content['nextStep'] == '验收' and saved.content['blocker'] == '等待审批'
        assert saved.content['status'] == 'in_progress'
    assert context.intent_model.inputs[0]['conversationTask']['activeDirectives'][0]['messageId'] == sent['messageId']


async def test_append_delta_preserves_original_and_repeated_new_events_while_replace_overwrites(setup):
    _, sessions, _, clients = setup
    original = '原有说明必须保留\n仓库：https://example.org/repo；今天有多个 commits。\n'
    addition = '部署文档已更新完成。'
    work = await create(clients['admin'], '上线Web', summary=original)
    rewritten = '原有说明必须保留\n仓库：https://example.org/repo；今天有多个 commits；' + addition
    context, _ = await runtime(setup, '给上线Web补充：部署文档也更新完了。', 'admin')
    context.intent_model = ScopedJudge(append=['summary'], append_values={'summary': addition})
    await read_work(context, work['id'])
    first = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'summary': rewritten})
    assert first['state'] == 'succeeded'
    # Retrying an already saved action reuses the receipt, not the text delta.
    assert (await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'summary': rewritten}))['id'] == first['id']
    async with sessions() as db:
        saved = await db.get(WorkItem, work['id'])
        assert saved.content['summary'] == original + addition and saved.revision == 2
        assert saved.content['summary'].count('原有说明必须保留') == 1
        assert saved.content['summary'].count('https://example.org/repo') == 1
    await close_task(context)
    again, _ = await runtime(setup, '部署文档又更新了一次，再追加同样一句“部署文档已更新完成。”', 'admin')
    again.intent_model = ScopedJudge(append=['summary'], append_values={'summary': addition})
    await read_work(again, work['id'])
    assert (await execute(again, step=1, action='update_work', target_id=work['id'], expected_revision=2, changes={'summary': addition}))['state'] == 'succeeded'
    async with sessions() as db:
        saved = await db.get(WorkItem, work['id'])
        assert saved.content['summary'] == original + addition + '\n' + addition
        assert saved.revision == 3
    await close_task(again)
    replace, _ = await runtime(setup, '把上线Web的说明全部替换为“重新制定部署方案”。', 'admin')
    replace.intent_model = ScopedJudge()
    await read_work(replace, work['id'])
    assert (await execute(replace, step=1, action='update_work', target_id=work['id'], expected_revision=3, changes={'summary': '重新制定部署方案'}))['state'] == 'succeeded'
    async with sessions() as db:
        assert (await db.get(WorkItem, work['id'])).content['summary'] == '重新制定部署方案'


@pytest.mark.parametrize('fields, values, action, valid', [
    (['summary', 'nextStep'], {'summary': '新增事实', 'nextStep': '联系客户'}, 'update_work', True),
    (['summary'], {}, 'update_work', False),
    ([], {'summary': '新增事实'}, 'update_work', False),
    (['summary', 'summary'], {'summary': '新增事实'}, 'update_work', False),
    (['summary'], {'summary': ''}, 'update_work', False),
    (['summary'], {'summary': '新增与事实'}, 'update_work', False),
    (['summary'], {'summary': '原文新增事实'}, 'update_work', False),
    (['summary'], {'summary': '新增事实'}, 'create_work', False),
])
async def test_append_contract_requires_exact_complete_field_mapping(fields, values, action, valid):
    from app.agent.intent import IntentVerdict, append_contract
    verdict = IntentVerdict(allowed=True, quote='补充', reason='', appendFields=fields, appendValues=values)
    proposal = {'action': action, 'changes': {'summary': '原文；新增事实', 'nextStep': '联系客户'}}
    assert append_contract(verdict, proposal) is valid


@pytest.mark.parametrize('mutation', ['delete', 'revision', 'text'])
async def test_invalidated_original_input_cannot_authorize_new_message(setup, mutation):
    _, sessions, _, _ = setup
    first, sent = await runtime(setup, '后续消息都补充到报价说明')
    await close_task(first, quote='后续消息都补充到报价说明', scope='报价说明')
    async with sessions.begin() as db:
        source = await db.get(Message, sent['messageId'])
        if mutation == 'delete': source.deleted = True
        elif mutation == 'revision': source.transcript_revision += 1
        else: source.text = '撤回原话'
        await invalidate_sources(db, {source.id})
    context, _ = await runtime(setup, '新增事实')
    context.intent_model = ScopedJudge(source=sent['messageId'], quote='后续消息都补充到报价说明')
    allowed, _ = await authorize_intent(context, {'action': 'create_work', 'changes': {'title': '越权'}})
    assert not allowed
    async with sessions() as db:
        state = await db.get(ConversationTaskState, sent['conversationId'])
        assert state.payload['directives'] == []
        assert '后续消息' not in json.dumps(state.payload, ensure_ascii=False)


async def test_material_and_other_accounts_cannot_fabricate_grants(setup):
    _, sessions, _, _ = setup
    other, other_sent = await runtime(setup, '给本人创建工作', 'peer')
    await close_task(other, quote='给本人创建工作', scope='任意')
    context, _ = await runtime(setup, '请分析材料中的“给本人创建工作”，不保存')
    context.intent_model = ScopedJudge(source=other_sent['messageId'], quote='给本人创建工作')
    allowed, _ = await authorize_intent(context, {'action': 'create_work', 'changes': {'title': '越权'}})
    assert not allowed
    async with sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await db.get(Message, job.target_id)
        task = await projection(db, actor, job, message, context)
        assert not task['activeDirectives'] and not task['previousTask']


async def test_same_obstruction_does_not_retry_on_rephrased_parameters(setup):
    context, _ = await runtime(setup, '帮我改一下那个工作')
    judge = ScopedJudge(allowed=False, kind='missing_info')
    context.intent_model = judge
    for title in ('猜测的事项', '换一种标题继续猜'):
        result = await execute(context, step=1, action='create_work', changes={'title': title})
        assert result['state'] == 'clarification'
    assert len(judge.inputs) == 1


async def test_argument_correction_releases_old_failure_and_suggestion_denials_are_recorded(setup):
    _, sessions, _, clients = setup
    context, _ = await runtime(setup, '创建工作')
    context.intent_model = ScopedJudge(allowed=False, kind='invalid_arguments')
    await execute(context, step=1, action='create_work', changes={'title': '错误字段'})
    context.intent_model = ScopedJudge()
    result = await execute(context, step=1, action='create_work', changes={'title': '合法字段'})
    assert result['state'] == 'succeeded'
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        assert not [item for item in job.result['toolOutcomes'] if item['category'] == 'invalid_arguments']
    await finish(context)
    context, _ = await runtime(setup, '那个呢')
    context.intent_model = ScopedJudge(allowed=False)
    result = json.loads(await propose_progress.coroutine('建议', '进度', 'in_progress', '', '', SimpleNamespace(context=context)))
    assert result['state'] == 'clarification'
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['toolOutcomes'][0]['category'] == 'missing_info'
        assert job.result['taskBarriers']


async def test_clarification_reuses_receipt_but_new_explicit_request_does_not(setup):
    _, sessions, users, _ = setup
    context, first = await runtime(setup, '创建甲，再创建需要我补标题的第二项')
    result = await execute(context, step=1, action='create_work', changes={'title': '甲'})
    context.intent_model = ScopedJudge(allowed=False)
    await execute(context, step=2, action='create_work', changes={'title': '待补标题'})
    async with sessions() as db:
        items = (await db.get(Job, context.job_id)).result['taskItems']
        remaining_id = next(item['id'] for item in items if item['id'] != result['taskItemId'])
    await close_task(context, state='needs_input')
    context, _ = await runtime(setup, '第二项叫乙')
    context.intent_model = ScopedJudge(resume=True)
    repeated = await execute(context, step=1, action='create_work', changes={'title': '甲的改写措辞'}, task_item_id=result['taskItemId'])
    second = await execute(context, step=2, action='create_work', changes={'title': '乙'}, task_item_id=remaining_id)
    assert repeated['id'] == result['id'] and second['state'] == 'succeeded'
    async with sessions() as db:
        rows = (await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == users['employee'].id))).all()
        assert len(rows) == 2 and all(row.task_id == first['messageId'] for row in rows)
    await close_task(context, relation='continue')
    context, _ = await runtime(setup, '再单独创建一份甲')
    context.intent_model = ScopedJudge()
    duplicate = await execute(context, step=1, action='create_work', changes={'title': '甲'})
    assert duplicate['id'] != result['id']
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 3


async def test_new_message_prevents_old_retry_and_fences_old_snapshot(setup):
    _, sessions, _, clients = setup
    context, first = await runtime(setup, '创建甲')
    await load(context)
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state, job.lease_until = 'awaiting_retry', None
    newer, _ = await runtime(setup, '原来的不要做了')
    await close_task(newer)
    retry = await clients['employee'].post('/api/v1/jobs/' + first['jobId'] + '/retry', json={})
    assert retry.status_code == 409 and retry.json()['error']['code'] == 'task_superseded'


async def test_unattempted_remaining_action_gets_new_identity_without_repeating_completed_item(setup):
    _, sessions, users, clients = setup
    first_work = await create(clients['employee'], '需求确认')
    second_work = await create(clients['employee'], '材料汇总', summary='第二批')
    first, sent = await runtime(setup, '把需求确认设为完成，材料汇总下一步改为发给客户')
    await read_work(first, first_work['id'])
    saved = await execute(first, step=1, action='update_work', target_id=first_work['id'], expected_revision=1, changes={'status': 'done'})
    await close_task(first, state='needs_input')
    context, _ = await runtime(setup, '材料汇总选择第二批那个，不要重复修改需求确认')
    judge = ScopedJudge(resume=True)
    context.intent_model = judge
    await read_work(context, second_work['id'])
    arguments = dict(step=1, action='update_work', target_id=second_work['id'], expected_revision=1, changes={'nextStep': '发给客户'})
    for _ in range(2):
        wrong = await execute(context, **arguments, task_item_id=saved['taskItemId'])
        assert wrong['state'] == 'clarification' and wrong['category'] == 'invalid_arguments'
        assert '需求确认' in wrong['message'] and '留空' in wrong['message']
    assert len(judge.inputs) == 1  # Repeated invalid parameters do not spend another model call.
    corrected = await execute(context, **arguments)
    assert corrected['state'] == 'succeeded' and corrected['taskItemId'] != saved['taskItemId']
    async with sessions() as db:
        actions = (await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == users['employee'].id))).all()
        assert len(actions) == 2 and all(row.task_id == sent['messageId'] for row in actions)
        assert (await db.get(WorkItem, first_work['id'])).revision == 2
        assert (await db.get(WorkItem, second_work['id'])).content['nextStep'] == '发给客户'


async def test_plain_override_keeps_scope_but_explicit_clear_revokes_it(setup):
    _, sessions, _, _ = setup
    first, sent = await runtime(setup, '后续更新报价说明')
    await close_task(first, quote='后续更新报价说明', scope='报价说明')
    current, _ = await runtime(setup, '这条先不保存')
    await close_task(current)
    async with sessions() as db:
        row = await db.get(ConversationTaskState, sent['conversationId'])
        assert row.payload['directives']
    current, _ = await runtime(setup, '以后都不保存了')
    await close_task(current, quote='以后都不保存了', change='clear')
    async with sessions() as db:
        row = await db.get(ConversationTaskState, sent['conversationId'])
        assert not row.payload['directives']


async def test_generation_and_confirmation_outcomes_follow_actual_receipts():
    job = SimpleNamespace(state='succeeded', result={'taskInterpretation': {'state': 'processing', 'remaining': ['报告生成中']}}, error='')
    card = {'id': 'one', 'state': 'running', 'label': '生成报告', 'job': {'state': 'running'}}
    assert derive(job, [card])['state'] == 'processing'
    assert derive(job, [{**card, 'state': 'succeeded'}])['state'] == 'completed'
    job.result['taskInterpretation'] = {'state': 'needs_confirmation', 'remaining': ['确认提交']}
    assert derive(job, [{**card, 'state': 'pending'}])['state'] == 'needs_confirmation'
    assert derive(job, [{**card, 'state': 'succeeded'}])['state'] == 'completed'
    assert derive(job, [{**card, 'job': {'state': 'failed'}, 'message': '报告生成失败'}])['state'] == 'blocked'
    job.state = 'running'
    job.result['taskOutcome'] = {'state': 'blocked'}
    assert derive(job)['state'] == 'processing'


async def test_failed_response_can_resume_saved_effect_from_new_message(setup):
    _, sessions, users, _ = setup
    context, first = await runtime(setup, '创建甲和乙')
    saved = await execute(context, step=1, action='create_work', changes={'title': '甲'})
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state, job.lease_until = 'awaiting_retry', None
    context, _ = await runtime(setup, '继续刚才没有完成的部分')
    context.intent_model = ScopedJudge(resume=True)
    result = await execute(context, step=1, action='create_work', changes={'title': '甲'})
    assert result['id'] == saved['id']
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 1


async def test_one_time_quote_in_directive_source_is_not_an_active_grant(setup):
    first, sent = await runtime(setup, '现在创建甲。以后只补充乙的说明。')
    await close_task(first, quote='以后只补充乙的说明', scope='乙.summary')
    context, _ = await runtime(setup, '一些额外材料')
    context.intent_model = ScopedJudge(source=sent['messageId'], quote='现在创建甲')
    allowed, _ = await authorize_intent(context, {'action': 'create_work', 'changes': {'title': '甲'}})
    assert not allowed


async def test_verified_revocation_survives_later_response_failure(setup):
    _, sessions, _, _ = setup
    first, sent = await runtime(setup, '以后帮我记录每条进展')
    await close_task(first, quote='以后帮我记录每条进展', scope='持续保存')
    context, _ = await runtime(setup, '现在创建乙，以后不要再保存')
    context.intent_model = ScopedJudge(interpretation={'directiveChange': 'clear', 'directiveQuote': '以后不要再保存'})
    result = await execute(context, step=1, action='create_work', changes={'title': '乙'})
    assert result['state'] == 'succeeded'
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state, job.lease_until = 'awaiting_retry', None
        state = await db.get(ConversationTaskState, sent['conversationId'])
        assert state.payload['directives'] == []
    context, _ = await runtime(setup, '一条新进展')
    snapshot = await load(context)
    assert not snapshot['directives']


async def test_task_outcome_hidden_from_non_owner_or_revoked_message(setup):
    from app.modules.messages.serializers import message_dto
    _, sessions, users, _ = setup
    context, sent = await runtime(setup, '私人任务')
    await load(context)
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state = 'succeeded'
        job.result = {**job.result, 'taskOutcome': {'state': 'needs_input', 'remaining': ['私有标题'], 'completed': [], 'reason': '私有原因'}}
        message = await db.get(Message, sent['messageId'])
        assert (await message_dto(db, message, users['admin']))['job']['taskOutcome'] is None
        message.access = {'team': True, 'invalidated': True, 'role': 'admin'}
        assert (await message_dto(db, message, users['employee']))['job']['taskOutcome'] is None


async def test_bound_continuing_target_survives_rename_and_rejects_same_name_replacement(setup):
    _, sessions, _, clients = setup
    original = await create(clients['employee'], '上线web', summary='旧说明')
    first, sent = await runtime(setup, '以后发的进展都补充到上线web的说明')
    quote = '以后发的进展都补充到上线web的说明'
    await close_task(first, quote=quote, scope='上线web.summary')
    context, _ = await runtime(setup, '第一份进展')
    context.intent_model = ScopedJudge(source=sent['messageId'], quote=quote, append=['summary'])
    await read_work(context, original['id'])
    assert (await execute(context, step=1, action='update_work', target_id=original['id'], expected_revision=1, changes={'summary': '第一份进展'}))['state'] == 'succeeded'
    await close_task(context)
    async with sessions.begin() as db:
        work = await db.get(WorkItem, original['id'])
        work.title = '上线新名称'
    replacement = await create(clients['employee'], '上线web')
    context, _ = await runtime(setup, '第二份进展')
    context.intent_model = ScopedJudge(source=sent['messageId'], quote=quote, append=['summary'])
    await read_work(context, replacement['id'])
    wrong = await execute(context, step=1, action='update_work', target_id=replacement['id'], expected_revision=1, changes={'summary': '第二份进展'})
    assert wrong['state'] == 'clarification'
    assert context.intent_model.inputs[0]['conversationTask']['activeDirectives'][0]['targetId'] == original['id']
    await read_work(context, original['id'])
    correct = await execute(context, step=2, action='update_work', target_id=original['id'], expected_revision=2, changes={'summary': '第二份进展'})
    assert correct['state'] == 'succeeded'


@pytest.mark.parametrize('same_target', [True, False])
async def test_inline_scope_binds_only_its_verified_target_and_finish_preserves_binding(setup, same_target):
    _, sessions, _, clients = setup
    original = await create(clients['employee'], '交付甲', summary='原始说明')
    quote = '以后补充都追加到交付甲的说明' if same_target else '以后补充都追加到交付乙的说明'
    context, sent = await runtime(setup, '这次给交付甲补充测试完成；' + quote)
    context.intent_model = ScopedJudge(append=['summary'], directive_target=original['id'] if same_target else '', directive_fields=['summary'],
        interpretation={'directiveChange': 'replace', 'directiveQuote': quote, 'directiveScope': '持续追加说明'})
    await read_work(context, original['id'])
    assert (await execute(context, step=1, action='update_work', target_id=original['id'], expected_revision=1, changes={'summary': '测试完成'}))['state'] == 'succeeded'
    # The final reviewer may reword the scope description without changing the original instruction.
    await close_task(context, quote=quote, scope='后续消息只追加指定工作的说明')
    async with sessions.begin() as db:
        state = await db.get(ConversationTaskState, sent['conversationId'])
        source = state.payload['directives'][0]
        assert source['targetId'] == (original['id'] if same_target else '')
        assert source['fields'] == (['summary'] if same_target else [])
        work = await db.get(WorkItem, original['id'])
        work.title = '交付甲已改名'
    if same_target:
        replacement = await create(clients['employee'], '交付甲')
        current, _ = await runtime(setup, '下一条进展')
        current.intent_model = ScopedJudge(source=sent['messageId'], quote=quote, append=['summary'])
        await read_work(current, replacement['id'])
        assert (await execute(current, step=1, action='update_work', target_id=replacement['id'], expected_revision=1, changes={'summary': '下一条进展'}))['state'] == 'clarification'
        await read_work(current, original['id'])
        assert (await execute(current, step=2, action='update_work', target_id=original['id'], expected_revision=2, changes={'summary': '下一条进展'}))['state'] == 'succeeded'


async def test_required_response_is_repaired_once_without_repeating_saved_operation(setup, monkeypatch):
    from test_business_actions import run_reply
    calls = []
    async def saved(context):
        await execute(context, step=1, action='create_work', changes={'title': '按计划推进'})
    async def repair(context, answer, reason, *, model=None):
        calls.append(reason)
        return '按计划推进仍在进行中。'
    class Judge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            fixed = payload['answer'] == '按计划推进仍在进行中。'
            return AIMessage(content=json.dumps({'issues': [] if fixed else [{'kind': 'fact', 'quote': payload['answer'], 'reason': '不能把创建工作当作工作完成', 'receipt_ids': [payload['currentActions'][0]['id']]}]}))
    monkeypatch.setattr('app.agent.response_repair.repair_response', repair)
    data = await run_reply(setup, '创建一个进行中的任务并解释状态', '已经做完了。', Judge(), before=saved)
    assert len(calls) == 1 and len(data['actions']) == 1
    assert '仍在进行中' in data['reply'] and '已经做完了' not in data['reply']
    assert data['job']['taskOutcome']['state'] == 'completed'
    assert data['job']['state'] == 'succeeded' and not data['job']['incompleteTask']


@pytest.mark.parametrize('state,remaining', [('completed', ['还要生成报告']), ('needs_input', []), ('needs_input', [' '])])
async def test_task_interpretation_rejects_inconsistent_completion(state, remaining):
    from app.modules.conversations.task_schemas import TaskInterpretation
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TaskInterpretation(state=state, remaining=remaining)


async def test_completed_receipt_cannot_become_waiting_for_future_input():
    job = SimpleNamespace(state='succeeded', error='', result={'incompleteTask': False, 'taskInterpretation': {'state': 'needs_input', 'remaining': []}})
    result = derive(job, [{'state': 'succeeded', 'label': '更新工作'}])
    assert result['state'] == 'completed' and result['remaining'] == [] and result['nextAction'] == 'none'


@pytest.mark.parametrize('blocked_source', ['interpretation', 'tool'])
async def test_partial_permission_denial_does_not_request_more_user_input(blocked_source):
    reason = '当前角色不能生成正式日报'
    result = {'incompleteTask': False, 'taskInterpretation': {'state': 'blocked', 'remaining': [reason]}} if blocked_source == 'interpretation' else {
        'toolOutcomes': [{'category': 'permission_denied', 'message': reason, 'label': '生成报告'}]}
    outcome = derive(SimpleNamespace(state='succeeded', error='', result=result), [{'state': 'succeeded', 'label': '创建工作'}])
    assert outcome['state'] == 'partial' and outcome['nextAction'] == 'none' and outcome['reason'] == reason


async def test_failed_required_prose_stays_partial_without_requesting_user_authorization():
    result = {'incompleteTask': True, 'completionIssue': 'response', 'taskInterpretation': {'state': 'completed', 'remaining': []}}
    outcome = derive(SimpleNamespace(state='awaiting_input', error='', result=result), [{'state': 'succeeded', 'label': '创建工作'}])
    assert outcome['state'] == 'partial' and outcome['nextAction'] == 'none'
    assert outcome['remaining'] and '答复' in outcome['reason']


async def test_missing_source_id_can_only_use_unique_exact_active_quote(setup):
    first, sent = await runtime(setup, '以后我的补充只追加到说明，不改状态')
    quote = '以后我的补充只追加到说明，不改状态'
    await close_task(first, quote=quote, scope='追加说明')
    context, _ = await runtime(setup, '一些本轮进展')
    context.intent_model = ScopedJudge(quote=quote)
    allowed, _ = await authorize_intent(context, {'action': 'update_work', 'changes': {'summary': '一些本轮进展'}})
    assert allowed
    context.intent_model = ScopedJudge(quote='以后要修改任何内容')
    rejected, _ = await authorize_intent(context, {'action': 'update_work', 'changes': {'status': 'done'}})
    assert not rejected


async def test_continuing_pending_suggestion_reuses_card_in_dto_and_feedback(setup):
    _, sessions, users, clients = setup
    first, sent = await runtime(setup, '先帮我整理待确认建议')
    first.intent_model = ScopedJudge(preview=True)
    original = json.loads(await propose_progress.coroutine('准备报价', '梳理规格', 'in_progress', '', '询价', SimpleNamespace(context=first)))
    await close_task(first, state='needs_confirmation')
    context, newer = await runtime(setup, '继续刚才的建议，先让我确认')
    context.intent_model = ScopedJudge(resume=True, preview=True)
    repeated = json.loads(await propose_progress.coroutine('改写但不是新的事项', '另一种说法', 'in_progress', '', '询价', SimpleNamespace(context=context)))
    assert repeated['draftId'] == original['draftId']
    await close_task(context, state='needs_confirmation', relation='continue')
    detail = (await clients['employee'].get('/api/v1/messages/' + newer['messageId'])).json()
    assert [draft['id'] for draft in detail['drafts']] == [original['draftId']]
    assert detail['job']['taskOutcome']['state'] == 'needs_confirmation'
    feedback = (await clients['employee'].get('/api/v1/jobs/' + newer['jobId'] + '/feedback')).json()
    assert feedback['taskOutcome']['state'] == 'needs_confirmation'
    response = await clients['employee'].post('/api/v1/progress-drafts/confirm', json={'items': [{'id': original['draftId'], 'expectedRevision': detail['drafts'][0]['revision']}]}, headers=keyed())
    assert response.status_code == 200, response.text
    updated = (await clients['employee'].get('/api/v1/messages/' + newer['messageId'])).json()
    assert updated['job']['taskOutcome']['state'] == 'completed'
    assert (await clients['employee'].get('/api/v1/jobs/' + newer['jobId'] + '/feedback')).json()['taskOutcome']['state'] == 'completed'
    async with sessions() as db:
        from app.modules.work.models import ProgressDraft
        assert await db.scalar(select(func.count()).select_from(ProgressDraft).where(ProgressDraft.owner_id == users['employee'].id)) == 1
