"""Replay the recorded high-B2 schema-error correction through real persistence."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.agent.actions.operations import execute
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkRevision
from app.tasks.feedback.outcomes import derive
from app.tasks.models import Job
from _support.agent.business_actions import create, read_work
from _support.agent.execution_permissions import mode_runtime
from _support.work.work_records import body

# Captured from job fa7fd0d9-1883-426d-bebe-7c767d96b851, not generated answers.
PLAN = {'changed': [{'field': 'status',
              'mode': 'set',
              'quotes': [{'messageId': 'f942f13d-2de5-41fd-a34d-196657084d06', 'text': '仅把这项工作的状态改为有阻碍'}],
              'value': 'blocked'},
             {'field': 'blocker',
              'mode': 'set',
              'quotes': [{'messageId': 'f942f13d-2de5-41fd-a34d-196657084d06', 'text': '阻碍写为“3份材料缺签字”'}],
              'value': None},
             {'field': 'nextStep',
              'mode': 'set',
              'quotes': [{'messageId': 'f942f13d-2de5-41fd-a34d-196657084d06', 'text': '下一步改为“联系负责人补齐签字”'}],
              'value': None},
             {'field': 'dueDate',
              'mode': 'set',
              'quotes': [{'messageId': 'f942f13d-2de5-41fd-a34d-196657084d06', 'text': '期限改为2026-10-30'}],
              'value': '2026-10-30'}],
 'preserved': ['title', 'summary', 'body', 'update', 'materials', 'removeMaterial']}
VERDICT = {'allowed': True,
 'quote': '仅把这项工作的状态改为有阻碍，阻碍写为“3份材料缺签字”，下一步改为“联系负责人补齐签字”，期限改为2026-10-30。正文、标题和材料保持不变，不记录独立进展。',
 'reason': '用户明确要求将本人工作《资料归档核对》状态改为有阻碍，阻碍写为“3份材料缺签字”，下一步改为“联系负责人补齐签字”，期限改为2026-10-30；目标由已验证工作引用唯一确定，拟议变更与请求一致。',
 'receiptOnly': True,
 'notRequested': False,
 'denialScope': 'other',
 'quoteMessageId': 'f942f13d-2de5-41fd-a34d-196657084d06',
 'resumeTask': False,
 'taskItemId': '',
 'newTaskItem': False,
 'continuingInstruction': False,
 'taskContext': {'goal': '将本人工作《资料归档核对》状态改为有阻碍，填写阻碍、下一步和期限，正文、标题和材料保持不变，不记录独立进展',
                 'relation': 'new',
                 'state': 'completed',
                 'remaining': [],
                 'directiveChange': 'keep',
                 'directiveQuote': '',
                 'directiveScope': ''},
 'directiveTargetId': '',
 'directiveFields': [],
 'appendValues': {},
 'failureKind': 'invalid_arguments',
 'recoveryOwner': 'none',
 'missingInputs': [],
 'materialSelection': {'mode': 'none',
                       'quote': '',
                       'messageId': '',
                       'references': [],
                       'previousId': '',
                       'destination': 'unselected',
                       'targetId': '',
                       'destinationEvidence': {'source': 'none', 'messageId': '', 'quote': ''}},
 'invalidFields': []}

class RecordedJudge:
    def __init__(self, *, plan=False, explicit=False):
        self.plan, self.explicit, self.inputs = plan, explicit, []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        value = deepcopy(PLAN if self.plan else VERDICT)
        old_message = 'f942f13d-2de5-41fd-a34d-196657084d06'
        value = json.loads(json.dumps(value).replace(old_message, payload['messageId']))
        if not self.plan:
            value['taskItemId'] = payload['proposedOperation'].get('taskItemId', '') if self.explicit else ''
        return AIMessage(content=json.dumps(value, ensure_ascii=False))


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [True, False])
async def test_recorded_invalid_work_correction(setup, explicit):
    work = await create(setup[3]['employee'], '资料归档核对', body=body('已核对12份材料，其中3份缺签字；补齐签字后才能归档。\n备注：原件由综合部保管。'))
    context, sent = await mode_runtime(setup, 'full', VERDICT['quote'])
    await read_work(context, work['id'])
    context.work_change_model = RecordedJudge(plan=True)
    context.intent_model = RecordedJudge(explicit=explicit)
    changes = dict(status='blocked', blocker='3份材料缺签字', nextStep='联系负责人补齐签字', dueDate='2026-10-30')
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    failed = await execute(context, **args, changes={**changes, 'title': {'unchanged': True}, 'body': {'unchanged': True}})
    assert failed['category'] == 'invalid_arguments'
    assert context.work_change_model.inputs == []
    result = await execute(context, **args, changes=changes, **({'task_item_id': failed['taskItemId']} if explicit else {}))
    assert result['state'] == 'succeeded'
    # Continue through the real worker delivery/final persistence, using the
    # recorded final response. No model network call or artificial terminal state.
    from langchain_openai import ChatOpenAI
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.tasks.processing.handlers import process_job
    class FinalModel(ChatOpenAI):
        async def _agenerate(self, messages, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=
                '已更新「资料归档核对」：\n\n- 状态：有阻碍\n- 阻碍：3份材料缺签字\n- 下一步：联系负责人补齐签字\n- 期限：2026-10-30\n\n标题、正文和材料均未变动，未另记录进展。'))])
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    async with AsyncPostgresSaver.from_conn_string(context.settings.checkpoint_url) as saver:
        await process_job(job, context.sessions, context.settings, saver,
                          model=FinalModel(model='controlled-no-network', api_key='test'))
    visible = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert visible['job']['state'] == 'succeeded'
    assert not visible['job']['incompleteTask']
    assert not visible['job']['operationFeedback']
    assert visible['job']['taskOutcome']['state'] == 'completed'
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.state == 'succeeded' and job.result['incompleteTask'] is False
        outcome = job.result['taskOutcome']
        print(json.dumps({'explicit': explicit, 'result': result, 'outcome': outcome, 'taskItems': job.result.get('taskItems'), 'toolOutcomes': job.result.get('toolOutcomes')}, ensure_ascii=False))
        assert result['state'] == 'succeeded'
        assert outcome['state'] == 'completed'
        assert not job.result['operationFeedback']
        assert all(item['state'] == 'succeeded' for item in job.result['taskItems'])
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == sent['messageId'])) == 1
        assert await db.scalar(select(func.count()).select_from(WorkRevision).where(WorkRevision.work_id == work['id'])) == 2
    after = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2
    assert all(after[key] == value for key, value in changes.items())
    assert all(after[key] == work[key] for key in ('title', 'body', 'materialIds'))



async def recovery_fixture(setup, *, text=None):
    work = await create(setup[3]['employee'], '资料归档核对', body=body('保留原正文'))
    context, sent = await mode_runtime(setup, 'full', text or VERDICT['quote'])
    await read_work(context, work['id'])
    context.work_change_model = RecordedJudge(plan=True)
    context.intent_model = RecordedJudge()
    changes = dict(status='blocked', blocker='3份材料缺签字', nextStep='联系负责人补齐签字', dueDate='2026-10-30')
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    failed = await execute(context, **args, changes={**changes, 'title': {'unchanged': True}, 'body': {'unchanged': True}})
    return context, sent, work, args, changes, failed


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['message', 'source_revision', 'documents', 'reference', 'prior_plan', 'receipt', 'permission_denied', 'conflict'])
async def test_correction_does_not_settle_unproven_old_attempt(setup, boundary):
    context, _, work, args, changes, failed = await recovery_fixture(setup)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        item = deepcopy(job.result['taskItems'][0])
        if boundary == 'message':
            item['userSource']['messageId'] = 'another-user-message'
        elif boundary == 'source_revision':
            item['schemaFailure']['sourceRevision'] += 1
        elif boundary == 'documents':
            item['schemaFailure']['documents'] = {'source-document': 2}
        elif boundary == 'reference':
            item['attemptedOperation']['sourceTokens'] = ['another-source']
            from app.core.digests import digest
            item['schemaFailure']['operation'] = digest(item['attemptedOperation'])
        elif boundary == 'prior_plan':
            item['schemaFailure']['priorPlans'] = [{'scope': 'other-plan', 'target': {'definitions': {'body': 'real-body-requirement'}}}]
        elif boundary == 'receipt':
            item['receiptId'], item['state'] = 'already-bound-receipt', 'pending'
        outcomes = deepcopy(job.result['toolOutcomes'])
        if boundary in ('permission_denied', 'conflict'):
            outcomes[0]['category'] = boundary
        job.result = {**job.result, 'taskItems': [item], 'toolOutcomes': outcomes}
    saved = await execute(context, **args, changes=changes)
    assert saved['state'] == 'succeeded'
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        job.state = 'succeeded'
        old = next(item for item in job.result['taskItems'] if item['id'] == failed['taskItemId'])
        assert not old.get('recoveredSchemaFailure')
        assert any(item.get('taskItemId') == failed['taskItemId'] for item in job.result['toolOutcomes'])
        assert derive(job, [saved])['state'] == 'partial'


@pytest.mark.asyncio
async def test_other_real_body_request_and_barrier_remain(setup):
    context, _, work, args, changes, failed = await recovery_fixture(setup)
    from app.agent.actions.task_outcomes import barrier
    await barrier(context, {'action': 'update_work', 'targetId': work['id'], 'taskItemId': failed['taskItemId'], 'changes': changes},
                  '旧范围引用拒绝', evidence='old-proof', kind='invalid_arguments')
    # A separate unresolved body operation on the same work must stay visible.
    other = await execute(context, **{**args, 'step': 2}, changes={'body': {'schemaVersion': 1, 'content': '另一个真实正文要求'}})
    await barrier(context, {'action': 'update_work', 'targetId': work['id'], 'taskItemId': other['taskItemId'], 'changes': {'body': {}}},
                  '正文尚未保存', evidence='other-proof', kind='invalid_arguments')
    saved = await execute(context, **args, changes=changes)
    assert saved['state'] == 'succeeded'
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        job.state = 'succeeded'
        failures = [entry for entry in job.result['toolOutcomes'] if entry['category'] != 'success']
        assert [entry['taskItemId'] for entry in failures] == [other['taskItemId']]
        assert {value['taskItemId'] for value in job.result['taskBarriers'].values()} == {other['taskItemId']}
        old = next(item for item in job.result['taskItems'] if item['id'] == failed['taskItemId'])
        assert old['recoveredSchemaFailure']['barriers']
        assert derive(job, [saved])['state'] == 'partial'


@pytest.mark.asyncio
@pytest.mark.parametrize('receipt_state', ['pending', 'failed', 'unavailable'])
async def test_unsuccessful_receipt_cannot_clear_schema_failure(setup, monkeypatch, receipt_state):
    context, _, work, args, changes, failed = await recovery_fixture(setup)
    if receipt_state == 'pending':
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.result = {**job.result, 'executionMode': 'ask'}
            from app.modules.members.models import Member
            member = await db.get(Member, context.owner_id)
            member.execution_mode = 'ask'
    elif receipt_state == 'failed':
        async def refused(db, actor, row, job, **kwargs):
            row.state, row.result = 'failed', {'message': '持久保存失败'}
        monkeypatch.setattr('app.agent.actions.operations.perform', refused)
    else:
        from app.agent.actions import operations
        original = operations.receipt
        async def unavailable(*args):
            result = await original(*args)
            return {**result, 'state': 'unavailable'}
        monkeypatch.setattr(operations, 'receipt', unavailable)
    saved = await execute(context, **args, changes=changes)
    assert saved['state'] == receipt_state
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        old = next(item for item in job.result['taskItems'] if item['id'] == failed['taskItemId'])
        assert not old.get('recoveredSchemaFailure')
        assert any(entry.get('taskItemId') == failed['taskItemId'] for entry in job.result['toolOutcomes'])


@pytest.mark.asyncio
@pytest.mark.parametrize(('window', 'mutation'), [('plan', 'new_attempt'), *[(window, mutation) for window in ('authorization', 'bound') for mutation in ('new_attempt', 'plan', 'selected_plan')]])
async def test_concurrent_attempt_or_plan_invalidates_work_recovery(setup, monkeypatch, window, mutation):
    import asyncio
    from app.agent.actions import operations
    context, sent, work, args, changes, failed = await recovery_fixture(setup)
    entered, resume = asyncio.Event(), asyncio.Event()
    class PausedJudge(RecordedJudge):
        async def ainvoke(self, messages):
            result = await super().ainvoke(messages)
            if window == 'authorization':
                entered.set()
                await resume.wait()
            return result
    context.intent_model = PausedJudge(explicit=True)
    if window == 'plan':
        class PausedPlan(RecordedJudge):
            async def ainvoke(self, messages):
                result = await super().ainvoke(messages)
                entered.set()
                await resume.wait()
                return result
        context.work_change_model = PausedPlan(plan=True)
    authorize = operations.authorize_intent
    async def paused(*args, **kwargs):
        result = await authorize(*args, **kwargs)
        if window == 'bound':
            entered.set()
            await resume.wait()
        return result
    monkeypatch.setattr(operations, 'authorize_intent', paused)
    writing = asyncio.create_task(execute(context, **args, changes=changes, task_item_id=failed['taskItemId']))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        if mutation == 'new_attempt':
            concurrent = await execute(context, **{**args, 'step': 2}, task_item_id=failed['taskItemId'],
                                       changes={**changes, 'body': {'schemaVersion': 1, 'content': '新增正文要求'}})
            assert concurrent['taskItemId'] == failed['taskItemId']
        else:
            async with context.sessions.begin() as db:
                job = await db.get(Job, context.job_id)
                key = 'workChangeRequirements' if mutation == 'selected_plan' else 'workChangeCandidates'
                state = deepcopy(job.result.get(key, job.result['workChangeCandidates']))
                state['targets'][work['id']]['definitions']['body'] = 'new-independent-plan'
                job.result = {**job.result, key: state}
    finally:
        resume.set()
    result = await writing
    assert result['category'] == 'conflict'
    assert '事项尝试已变化' in result['diagnostic']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert not await db.scalar(select(BusinessAction).where(BusinessAction.message_id == sent['messageId']))
        assert all(not item.get('recoveredSchemaFailure') for item in job.result['taskItems'])


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [True, False])
async def test_recovered_subitem_receipt_survives_partial_task_continuation(setup, explicit):
    from _support.agent.business_actions import runtime
    from _support.agent.conversation_task_state import ScopedJudge, close_task
    from app.agent.actions.task_items import reference_error
    text = VERDICT['quote'] + '另外新建一项工作，标题是第二项，正文是整理资料。'
    context, sent, work, args, changes, failed = await recovery_fixture(setup, text=text)
    context.intent_model = RecordedJudge(explicit=explicit)
    saved = await execute(context, **args, changes=changes, **({'task_item_id': failed['taskItemId']} if explicit else {}))
    assert saved['state'] == 'succeeded'
    other = await execute(context, step=2, action='create_work', changes={'title': '第二项', 'body': {'schemaVersion': 1, 'content': '整理资料'}})
    assert other['state'] == 'failed'
    from app.tasks.feedback.items import collect
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        projected = collect(job)
        assert {item['id'] for item in projected} == {saved['taskItemId'], other['taskItemId']}
        assert next(item for item in projected if item['id'] == other['taskItemId'])['state'] != 'succeeded'
        assert any(entry.get('taskItemId') == other['taskItemId'] for entry in job.result['toolOutcomes'])
        assert any(item['id'] == failed['taskItemId'] for item in job.result['taskItems'])
    await close_task(context, state='needs_input')
    followup, _ = await runtime(setup, '继续刚才的任务，先核对已经保存的工作，不要重复写入')
    await read_work(followup, work['id'])
    followup.intent_model = ScopedJudge(resume=True)
    replay = await execute(followup, **{**args, 'expected_revision': 2}, changes=changes, task_item_id=saved['taskItemId'])
    print('SUBITEM_REPLAY', json.dumps(replay, ensure_ascii=False))
    assert replay.get('id') == saved['id'], replay
    assert (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()['revision'] == 2
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        original = next(item for item in job.result['taskItems'] if item['id'] == saved['taskItemId'])
    proposal = {'action': 'update_work', 'targetId': work['id'], 'changes': changes, 'kind': 'weekly'}
    assert not reference_error([original], original['id'], proposal)
    if not explicit:
        return  # This executed item has no retired invalid attempts.
    mismatch = deepcopy(original)
    mismatch['recoveredSchemaFailure']['receiptId'] = 'unrelated-receipt'
    assert reference_error([mismatch], mismatch['id'], proposal)
    mismatch = deepcopy(original)
    mismatch['invalidAttempts'].append({**mismatch['attemptedOperation'], 'changes': {'body': {'unrelated': True}}})
    assert reference_error([mismatch], mismatch['id'], proposal)


@pytest.mark.asyncio
@pytest.mark.parametrize('mismatch', ['action', 'target', 'member', 'pending_child'])
async def test_wrong_receipt_identity_cannot_settle_old_schema_failure(setup, monkeypatch, mismatch):
    """Authenticated receipt projection, not model text, must prove recovery."""
    from app.agent.actions import operations
    from fastapi import HTTPException
    context, _, work, args, changes, failed = await recovery_fixture(setup)
    other = await create(setup[3]['employee'], '另一真实目标', body=body('不同目标正文'))
    original = operations.receipt
    observations = []
    pending = None
    if mismatch == 'pending_child':
        from _support.agent.business_actions import Judge
        from app.db.base import now
        from zoneinfo import ZoneInfo
        context.intent_model = Judge()
        pending = await execute(context, step=2, action='generate_report', report_kind='weekly',
                                report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
        assert pending['state'] == 'running' and pending['job']['state'] == 'queued'
        context.intent_model = RecordedJudge()

    async def substituted(context, db, actor, job, row):
        original_action, original_owner, original_result = row.action, row.owner_id, row.result
        try:
            if mismatch == 'action':
                row.action = 'create_work'
            elif mismatch == 'target':
                row.result = {**row.result, 'objectId': other['id'], 'revision': 1}
            elif mismatch == 'member':
                row.owner_id = setup[2]['peer'].id
            result = await original(context, db, actor, job, row)
            if mismatch == 'pending_child':
                # Read the actual admitted child through the production DTO.
                child_receipt = await db.get(BusinessAction, pending['id'])
                result = await original(context, db, actor, job, child_receipt)
                assert result['state'] == 'running' and result['job']['state'] == 'queued'
            observations.append(result)
            return result
        except HTTPException as error:
            observations.append({'status': error.status_code})
            raise
        finally:
            row.action, row.owner_id, row.result = original_action, original_owner, original_result

    monkeypatch.setattr(operations, 'receipt', substituted)
    if mismatch == 'member':
        with pytest.raises(HTTPException) as rejected:
            await execute(context, **args, changes=changes)
        assert rejected.value.status_code == 404
        assert observations == [{'status': 404}]
        returned = {'state': 'unavailable'}
    else:
        returned = await execute(context, **args, changes=changes)
    assert observations
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        old = next(item for item in job.result['taskItems'] if item['id'] == failed['taskItemId'])
        assert not old.get('recoveredSchemaFailure')
        assert any(entry.get('taskItemId') == failed['taskItemId'] for entry in job.result['toolOutcomes'])
        job.state = 'succeeded'
        assert derive(job, [returned])['state'] != 'completed'
