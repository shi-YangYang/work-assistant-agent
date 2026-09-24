from fastapi import HTTPException
from paa_server.agent.intent import authorize_intent
from paa_server.core.digests import digest
from paa_server.core.versions import version
from paa_server.modules.messages.models import Message
from paa_server.modules.operations.models import BusinessAction
from paa_server.modules.operations.receipts import action_dto
from paa_server.modules.operations.rules import ACTIONS, CONFIRM, LABELS, REPORT_FIELDS, WORK_FIELDS
from paa_server.modules.operations.service import perform
from paa_server.modules.operations.targets import preview, read_target, source_check
from paa_server.modules.reports.sources import report_fact_basis
from paa_server.modules.work.models import WorkItem
from paa_server.security.access import scope as business_scope, valid as business_valid
from paa_server.security.ownership import owned
from sqlalchemy import select


async def execute(context, **arguments):
    """Keep operation feedback even if a later model/review request fails."""
    from paa_server.tasks.lease import lease
    async def remember(result):
        step = arguments.get('step')
        if not isinstance(step, int) or not 1 <= step <= 8:
            return
        request_key = digest({key: value for key, value in arguments.items() if key not in ('step', 'expected_revision')})
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            keys = job.result.get('operationFeedbackKeys', {})
            resolved = result.get('state') in ('succeeded', 'pending', 'running')
            feedback = [item for item in job.result.get('operationFeedback', []) if item['step'] != step and not (resolved and keys.get(str(item['step'])) == request_key)]
            keys = {str(item['step']): keys.get(str(item['step']), '') for item in feedback}
            if result.get('state') in ('failed', 'conflict', 'clarification', 'waiting'):
                feedback.append({'step': step, 'action': arguments.get('action', ''), 'label': LABELS.get(arguments.get('action'), '业务操作'), 'state': result['state'], 'message': str(result.get('message', ''))[:500]})
                keys[str(step)] = request_key
            job.result = {**job.result, 'operationFeedback': sorted(feedback, key=lambda item: item['step']), 'operationFeedbackKeys': keys}
            # Announce only committed outcomes. The endpoint resolves authorized
            # DTOs on each read instead of copying tool arguments into SSE.
            from paa_server.tasks.feedback_state import update_feedback
            update_feedback(job, 'operating', '')
    try:
        result = await _execute(context, **arguments)
    except HTTPException as error:
        await remember({'state': 'conflict' if error.status_code == 409 else 'failed', 'message': error.detail['message']})
        raise
    except ValueError:
        await remember({'state': 'clarification', 'message': '请核对必要内容、日期和字段，操作未执行。'})
        raise
    else:
        await remember(result)
        return result


async def _execute(context, *, step, action, target_id='', expected_revision=0, changes=None, report_kind='daily', report_date='', obligation_id='', source_tokens=None, submit_after=False, requires_step=None):
    from paa_server.tasks.lease import lease
    from paa_server.agent.conversation_context import request_text
    if action not in ACTIONS or not 1 <= step <= 8 or requires_step is not None and not 1 <= requires_step < step:
        return {'state': 'failed', 'message': '操作或步骤无效'}
    changes = changes or {}
    fields = WORK_FIELDS if action in ('create_work', 'update_work') else REPORT_FIELDS if action == 'edit_report' else frozenset()
    if changes.keys() - fields or submit_after and action != 'generate_report':
        return {'state': 'failed', 'message': '包含本次操作不支持的字段'}
    params = {'targetId': target_id, 'expectedRevision': expected_revision, 'changes': changes, 'kind': report_kind, 'date': report_date, 'obligationId': obligation_id, 'sourceTokens': sorted(source_tokens or []), 'submitAfter': submit_after, 'requiresStep': requires_step}
    fingerprint = digest({'action': action, **params})
    identity = {'action': action, 'target': target_id, 'changes': changes, 'kind': report_kind, 'date': report_date, 'submitAfter': submit_after}
    if action == 'create_work':
        identity = {'action': action, 'title': str(changes.get('title', '')).strip().casefold()}
    intent_key = digest(identity)
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'message':
            return {'state': 'failed', 'message': '当前任务不能执行聊天操作'}
        prior = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, ((BusinessAction.step == step) | (BusinessAction.intent_key == intent_key))))
        if prior:
            # A stable ordinal binds retries even if the provider changes its call ID.
            if prior.digest != fingerprint:
                return {'state': 'conflict', 'message': '这一操作步骤已有保存结果，本次新参数未写入。使用 existingOperation 回答，不再重试该步骤；进一步修改需新的用户请求。', 'existingOperation': await action_dto(db, actor, prior)}
            return await action_dto(db, actor, prior)
        if requires_step:
            predecessor = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, BusinessAction.step == requires_step))
            if not predecessor or predecessor.state != 'succeeded':
                return {'state': 'waiting', 'message': '前置操作尚未成功，本步骤未执行'}
        message = await owned(db, Message, job.target_id, actor)
        target = await read_target(db, actor, action, target_id) if action not in ('create_work', 'generate_report') else None
        if target:
            version(target, expected_revision)
            if context.read_versions.get(target.id) != expected_revision:
                return {'state': 'conflict', 'message': '请先读取目标的最新版本，再决定修改'}
        if action == 'generate_report' and actor.role != 'employee':
            return {'state': 'failed', 'message': '管理员不生成或代交员工报告'}
        candidates = []
        if isinstance(target, WorkItem):
            same_name = (await db.scalars(select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id == actor.id, WorkItem.deleted.is_(False), WorkItem.title == target.title).limit(21))).all()
            candidates = [{'id': w.id, 'title': w.title, 'summary': w.content.get('summary', ''), 'createdAt': w.created_at.isoformat(), 'dueDate': w.content.get('dueDate')} for w in same_name if await business_valid(db, actor, w.access, retained=True)]
        effect = 'prepare_confirmation' if action in CONFIRM else 'enqueue_report' if action == 'generate_report' else 'save'
        proposal = {'targetCandidates': candidates, 'action': action, 'effect': effect, 'target': target.title if isinstance(target, WorkItem) else f'{target.period} {target.kind}' if target else '', **params}
        if action == 'edit_report':
            proposal['targetContent'] = target.content
            proposal['reportSourceFacts'] = await report_fact_basis(db, actor, target)
    if action == 'edit_report':
        # Permission to rewrite and factual correctness are different questions.
        # Check the entire resulting report independently before any write.
        from paa_server.agent.reports import verify_report
        try:
            await verify_report(context, {
                'confirmed': proposal['reportSourceFacts']['items'],
                'originalReport': proposal['targetContent'],
                'mode': 'rewrite',
                'userRequest': request_text(message, job),
            }, {**proposal['targetContent'], **changes}, context.intent_model)
        except ValueError as error:
            return {'state': 'clarification', 'message': str(error)}
    allowed, reason = await authorize_intent(context, proposal)
    if not allowed:
        return {'state': 'clarification', 'message': reason or '请明确要执行的操作和对象，业务尚未更改'}
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        prior = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, ((BusinessAction.step == step) | (BusinessAction.intent_key == intent_key))))
        if prior:
            return await action_dto(db, actor, prior) if prior.digest == fingerprint else {'state': 'conflict', 'message': '操作内容已变化'}
        message = await owned(db, Message, job.target_id, actor, lock=True)
        row = BusinessAction(company_id=actor.company_id, owner_id=actor.id, message_id=message.id, conversation_id=message.conversation_id, step=step, action=action, digest=fingerprint, intent_key=intent_key, params={**params, 'sourceRevision': message.transcript_revision, 'documents': context.document_versions}, access=job.access or business_scope(actor))
        db.add(row)
        await db.flush()
        try:
            async with db.begin_nested():
                await source_check(db, actor, row)
                if action in CONFIRM:
                    value = await preview(db, actor, row)
                    row.result = {'previewDigest': digest(value), 'objectType': 'work' if action.endswith('work') else 'report', 'objectId': target_id}
                    row.state = 'pending'
                else:
                    await perform(db, actor, row, job)
        except HTTPException as error:
            row.state = 'conflict' if error.status_code == 409 else 'failed'
            row.params = {}
            row.result = {'message': error.detail['message']}
        if step == 1 and digest(proposal) in context.receipt_candidates and row.state in ('succeeded', 'pending', 'running'):
            row.result = {**row.result, 'receiptOnly': True, 'receiptInput': digest({'text': request_text(message, job), 'sourceRevision': message.transcript_revision, 'documents': context.document_versions})}
        await db.flush()
        return await action_dto(db, actor, row)
