from fastapi import HTTPException
from app.agent.intent import authorize_intent
from app.core.digests import digest
from app.core.versions import version
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.operations.receipts import action_dto
from app.modules.operations.rules import ACTIONS, CONFIRM, LABELS, REPORT_FIELDS, WORK_FIELDS
from app.modules.operations.service import perform
from app.modules.operations.targets import preview, read_target, source_check
from app.modules.reports.sources import report_fact_basis
from app.modules.work.models import WorkItem
from app.security.access import scope as business_scope, valid as business_valid
from app.security.ownership import owned
from sqlalchemy import select


async def receipt(context, db, actor, job, row):
    result = await action_dto(db, actor, row)
    if context.node_retry:
        from app.tasks.node_execution import active_node
        from app.tasks.node_state import execution, save
        node = active_node.get()
        if node and node[1] == 'tool':
            state = execution(job)
            current = next(item for item in state['nodes'] if item['id'] == node[0])
            # The reference and business effect commit together. A worker can
            # recover it even if no tool output/read version was journaled.
            current['receiptId'] = row.id
            save(job, state)
    return result


async def execute(context, **arguments):
    """Keep operation feedback even if a later model/review request fails."""
    from app.tasks.lease import lease
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
            from app.tasks.feedback_state import update_feedback
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
        if result.get('objectRevision') and result.get('objectId'):
            context.read_versions[result['objectId']] = result['objectRevision']
        return result


async def _execute(context, *, step, action, target_id='', expected_revision=0, changes=None, report_kind='daily', report_date='', obligation_id='', source_tokens=None, submit_after=False, requires_step=None, copy_index=1, deliverable_id='', deliverable_revision=0, item_id='', shared_attachment_ids=None):
    from app.tasks.lease import lease
    from app.agent.conversation_context import request_text
    if action not in ACTIONS or not 1 <= step <= 8 or requires_step is not None and not 1 <= requires_step < step:
        return {'state': 'failed', 'message': '操作或步骤无效'}
    if not isinstance(copy_index, int) or not 1 <= copy_index <= 8 or action != 'create_work' and copy_index != 1:
        return {'state': 'failed', 'message': '创建副本编号无效'}
    changes = changes or {}
    fields = WORK_FIELDS if action in ('create_work', 'update_work') else REPORT_FIELDS if action == 'edit_report' else frozenset()
    if changes.keys() - fields or submit_after and action != 'generate_report':
        return {'state': 'failed', 'message': '包含本次操作不支持的字段'}
    params = {'targetId': target_id, 'expectedRevision': expected_revision, 'changes': changes, 'kind': report_kind, 'date': report_date, 'obligationId': obligation_id, 'sourceTokens': sorted(source_tokens or []), 'submitAfter': submit_after, 'requiresStep': requires_step}
    if deliverable_id or deliverable_revision or item_id:
        if action not in ('create_work', 'update_work') or not deliverable_id or not item_id or deliverable_revision < 1:
            return {'state': 'failed', 'message': '成果关联需要准确的版本与一个条目'}
        params['deliverableReference'] = {'id': deliverable_id, 'revision': deliverable_revision, 'itemIds': [item_id]}
    if shared_attachment_ids:
        if action not in ('create_work', 'update_work'):
            return {'state': 'failed', 'message': '仅工作支持附带材料'}
        params['sharedAttachmentIds'] = sorted(shared_attachment_ids)
    if copy_index > 1:
        params['copyIndex'] = copy_index
    fingerprint = digest({'action': action, **params})
    identity = {'action': action, 'target': target_id, 'changes': changes, 'kind': report_kind, 'date': report_date, 'submitAfter': submit_after}
    if copy_index > 1:
        identity['copyIndex'] = copy_index
    if deliverable_id:
        identity['deliverableReference'] = params['deliverableReference']
    if shared_attachment_ids:
        identity['sharedAttachmentIds'] = params['sharedAttachmentIds']
    intent_key = digest(identity)
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'message':
            return {'state': 'failed', 'message': '当前任务不能执行聊天操作'}
        prior = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, ((BusinessAction.step == step) | (BusinessAction.intent_key == intent_key) | (BusinessAction.digest == fingerprint))))
        if prior:
            # A stable ordinal binds retries even if the provider changes its call ID.
            if prior.digest != fingerprint:
                return {'state': 'conflict', 'message': '这一操作步骤已有保存结果，本次新参数未写入。使用 existingOperation 回答，不再重试该步骤；进一步修改需新的用户请求。', 'existingOperation': await action_dto(db, actor, prior)}
            return await receipt(context, db, actor, job, prior)
        if requires_step:
            predecessor = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, BusinessAction.step == requires_step))
            if not predecessor or predecessor.state != 'succeeded':
                return {'state': 'waiting', 'message': '前置操作尚未成功，本步骤未执行'}
        message = await owned(db, Message, job.target_id, actor)
        target = await read_target(db, actor, action, target_id) if action not in ('create_work', 'generate_report') else None
        if action == 'edit_report':
            from app.tasks.models import Job
            generation = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, BusinessAction.action == 'generate_report', BusinessAction.result['objectId'].astext == target.id).limit(1))
            pending = await db.get(Job, generation.result['jobId']) if generation else None
            if pending and pending.state in ('queued', 'running'):
                # The same owner cannot run this queued report until the chat
                # finishes. Editing its empty draft would make the real output
                # a candidate and can trap the planner in a polling loop.
                return {**(await action_dto(db, actor, generation)), 'message': '本次写作要求已交给报告生成任务；请结束本轮等待生成，不要编辑空草稿或轮询结果。'}
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
        selected = None
        if deliverable_id:
            from app.modules.deliverables.queries import check_reference
            from app.modules.deliverables.serializers import detail
            if context.deliverable_reads.get(deliverable_id, job.result.get('deliverableReads', {}).get(deliverable_id)) != deliverable_revision:
                return {'state': 'conflict', 'message': '请先读取所用成果的准确版本和条目'}
            item, record = await check_reference(db, actor, params['deliverableReference'], message.conversation_id)
            selected = await detail(db, actor, item, record)
            selected['items'] = [entry for entry in record.items if entry['id'] == item_id]
            selected.pop('body', None)
            linked = [link for link in selected['links'] if link['itemId'] == item_id and not link['unavailable']]
            if action == 'create_work' and linked and copy_index == 1:
                return {'state': 'conflict', 'message': '该方案条目已加入工作，请使用已有工作；仅用户明确要求另建副本时使用 copy_index=2 或更高编号。', 'linkedWorks': linked}
            if action == 'update_work' and target_id not in [link['workId'] for link in linked]:
                return {'state': 'conflict', 'message': '目标工作不属于该方案条目，请核对关联'}
        from app.modules.operations.publication import selected_attachments
        attachments = await selected_attachments(db, actor, shared_attachment_ids or [], message.conversation_id)
        effect = 'prepare_confirmation' if action in CONFIRM else 'enqueue_report' if action == 'generate_report' else 'save'
        proposal = {'targetCandidates': candidates, 'action': action, 'effect': effect, 'target': target.title if isinstance(target, WorkItem) else f'{target.period} {target.kind}' if target else '', **params}
        if selected:
            proposal['deliverableSelection'] = selected
        if attachments:
            proposal['sharedAttachments'] = attachments
        if action == 'edit_report':
            proposal['targetContent'] = target.content
            proposal['reportSourceFacts'] = await report_fact_basis(db, actor, target, full=True)
            if not proposal['reportSourceFacts']['complete']:
                return {'state': 'clarification', 'message': '报告来源不完整或访问权限已变化，本次未修改，请先核对来源。'}
    if action == 'edit_report':
        # Permission to rewrite and factual correctness are different questions.
        # Check the entire resulting report independently before any write.
        from app.agent.reports import verify_report
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
        if digest(proposal) in context.unrequested_actions:
            return {'state': 'not_requested', 'message': reason or '本次未要求该操作，已跳过；继续回应原请求即可，无需要求用户授权多余操作。'}
        return {'state': 'clarification', 'message': reason or '请明确要执行的操作和对象，业务尚未更改'}
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        prior = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, ((BusinessAction.step == step) | (BusinessAction.intent_key == intent_key) | (BusinessAction.digest == fingerprint))))
        if prior:
            return await receipt(context, db, actor, job, prior) if prior.digest == fingerprint else {'state': 'conflict', 'message': '操作内容已变化'}
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
        return await receipt(context, db, actor, job, row)
