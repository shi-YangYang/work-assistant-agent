from fastapi import HTTPException
from app.agent.actions.intent import authorize_intent
from app.core.digests import digest
from app.core.versions import version
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.operations.receipts import action_dto
from app.modules.operations.policy.rules import ACTIONS, CONFIRM, LABELS, REPORT_FIELDS, WORK_FIELDS
from app.modules.operations.service import perform
from app.modules.operations.targets import preview, read_target, source_check
from app.modules.reports.generation.sources import report_fact_basis
from app.modules.work.models import WorkItem
from app.security.access import scope as business_scope, valid as business_valid
from app.security.ownership import owned
from sqlalchemy import select


def same_request(row, action, params, fingerprint):
    if row.digest == fingerprint:
        return True
    # A lost response can make the model retry against the version produced by
    # its own committed update. Recover only that exact request: the full digest
    # still proves every content, dependency and publication argument unchanged.
    revision = row.result.get('revision')
    if (action != 'update_work' or row.action != action or row.state != 'succeeded'
            or not isinstance(revision, int) or revision < 2
            or row.result.get('objectId') != params['targetId']
            or params['expectedRevision'] != revision):
        return False
    return row.digest == digest({'action': action, **params, 'expectedRevision': revision - 1})


async def receipt(context, db, actor, job, row):
    result = await action_dto(db, actor, row)
    if context.node_retry:
        from app.tasks.nodes.node_execution import active_node
        from app.tasks.nodes.node_state import execution, save
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
        from app.agent.actions.task_outcomes import remember as remember_outcome
        outcome_arguments = {key: value for key, value in arguments.items() if key != 'task_item_id'}
        if result.get('taskItemId'):
            outcome_arguments['task_item_id'] = result['taskItemId']
        await remember_outcome(context, arguments.get('action', ''), outcome_arguments, result)
        step = arguments.get('step')
        if not isinstance(step, int) or not 1 <= step <= 8:
            return
        async with context.sessions.begin() as db:
            job, context_actor = await lease(db, context)
            if context.node_retry:
                from app.tasks.nodes.node_execution import active_node
                from app.tasks.nodes.node_state import execution, save
                current_node = active_node.get()
                if current_node and current_node[1] == 'tool':
                    state = execution(job)
                    node = next(item for item in state['nodes'] if item['id'] == current_node[0])
                    node['requestKey'] = digest({key: value for key, value in arguments.items() if key not in ('step', 'expected_revision', 'task_item_id')})
                    save(job, state)
            # Announce only committed outcomes. The endpoint resolves authorized
            # DTOs on each read instead of copying tool arguments into SSE.
            from app.tasks.feedback.feedback_state import update_feedback
            update_feedback(job, 'operating', '')
            if arguments.get('action') == 'update_work' and job.result.get('workChangeRequirements'):
                from app.modules.operations.receipts import message_actions
                from app.tasks.feedback.work_requirements import remaining
                cards = [result]
                missing = remaining(job, cards, include_pending=True)
                if missing or any(entry.get('planRejection') for entry in job.result.get('toolOutcomes', [])):
                    message = await owned(db, Message, job.target_id, context_actor)
                    cards = await message_actions(db, context_actor, message)
                    missing = remaining(job, cards, include_pending=True)
                from app.tasks.feedback.outcomes import reconcile
                reconcile(job, cards)
                return missing
    try:
        result = await _execute(context, **arguments)
    except HTTPException as error:
        if arguments.get('action') == 'update_work' and isinstance(error.detail, dict) and error.detail.get('code') == 'revision_conflict':
            identifier, expected = arguments.get('target_id'), arguments.get('expected_revision')
            async with context.sessions.begin() as db:
                job, actor = await lease(db, context)
                work = await owned(db, WorkItem, identifier, actor)
                from app.security.access import require
                await require(db, actor, work.access, retained=True)
                if context.read_versions.get(identifier) == expected and work.revision != expected:
                    context.refresh_work_versions[identifier] = expected
                    if context.node_retry:
                        from app.tasks.nodes.node_state import execution, save
                        state = execution(job)
                        state['readVersions'] = dict(context.read_versions)
                        state['refreshWorkVersions'] = dict(context.refresh_work_versions)
                        save(job, state)
        await remember({'state': 'conflict' if error.status_code == 409 else 'failed', 'category': 'permission_denied' if error.status_code in (403, 404) else 'conflict' if error.status_code == 409 else 'invalid_arguments', 'message': error.detail['message']})
        raise
    except ValueError:
        await remember({'state': 'failed', 'category': 'invalid_arguments', 'message': '请核对必要内容、日期和字段，操作未执行。'})
        raise
    else:
        missing = await remember(result)
        if result.get('objectRevision') and result.get('objectId'):
            context.read_versions[result['objectId']] = result['objectRevision']
        if missing:
            result = {**result, 'remainingChanges': missing,
                      'planningNote': '此回执仅覆盖已保存的原子步骤；按原用户要求继续剩余字段，不重复已成功操作。每一步仍须正常授权，不能把未尝试步骤说成缺少用户信息。'}
        return result


async def _execute(context, *, step, action, target_id='', expected_revision=0, changes=None, report_kind='daily', report_date='', obligation_id='', source_tokens=None, submit_after=False, requires_step=None, copy_index=1, deliverable_id='', deliverable_revision=0, item_id='', shared_attachment_ids=None, task_item_id=''):
    from app.tasks.lease import lease
    from app.agent.context.references.conversation_context import request_text
    if action not in ACTIONS or not 1 <= step <= 8 or requires_step is not None and not 1 <= requires_step < step:
        return {'state': 'failed', 'message': '操作或步骤无效'}
    if not isinstance(copy_index, int) or not 1 <= copy_index <= 8 or action != 'create_work' and copy_index != 1:
        return {'state': 'failed', 'message': '创建副本编号无效'}
    changes = changes or {}
    fields = WORK_FIELDS if action in ('create_work', 'update_work') else REPORT_FIELDS if action == 'edit_report' else frozenset()
    if changes.keys() - fields or submit_after and action != 'generate_report':
        return {'state': 'failed', 'message': '包含本次操作不支持的字段'}
    if action in ('create_work', 'update_work'):
        from app.modules.work.records.record_schemas import AgentWorkChanges
        AgentWorkChanges.model_validate(changes)
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
    request_params = params
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
            if not same_request(prior, action, request_params, fingerprint):
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
            return {'state': 'failed', 'category': 'permission_denied', 'message': '管理员不生成或代交员工报告'}
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
        from app.modules.operations.mutations.publication import selected_attachments
        attachments = await selected_attachments(db, actor, shared_attachment_ids or [], message.conversation_id)
        from app.modules.operations.policy.execution_policy import mode_for, decide
        mode = await mode_for(db, job)
        effect = 'prepare_confirmation' if decide(mode, action, changes=changes).outcome == 'ask' else 'enqueue_report' if action == 'generate_report' else 'save'
        proposal = {'targetCandidates': candidates, 'action': action, 'requestStep': step, 'effect': effect, 'target': target.title if isinstance(target, WorkItem) else f'{target.period} {target.kind}' if target else '', **params}
        if task_item_id:
            proposal['taskItemId'] = task_item_id
        if isinstance(target, WorkItem):
            from app.modules.work.serializers import work_content
            proposal['targetContent'] = work_content(target.content, target.id)
        if action in ('create_work', 'update_work') and changes.get('bodyEdits'):
            from app.modules.work.content.checklist import edit_previews
            details = edit_previews(proposal.get('targetContent', {}).get('body', {'schemaVersion': 1, 'content': []}), changes['bodyEdits'])
            if any(edit['action'] == 'set_checked' for edit in details):
                proposal['workContentChanges'] = [edit for edit in details if edit['action'] == 'set_checked']
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
                'workContextsForPlansOnly': proposal['reportSourceFacts']['workContextsForPlansOnly'],
                'originalReport': proposal['targetContent'],
                'mode': 'rewrite',
                'userRequest': request_text(message, job),
            }, {**proposal['targetContent'], **changes}, context.intent_model)
        except ValueError as error:
            return {'state': 'clarification', 'message': str(error)}
    allowed, reason = await authorize_intent(context, proposal)
    if not allowed:
        if digest(proposal) in context.unrequested_actions or context.authorization_outcomes.get(digest(proposal)) == 'not_requested':
            return {'state': 'not_requested', 'message': reason or '本次未要求该操作，已跳过；继续回应原请求即可，无需要求用户授权多余操作。'}
        category = context.authorization_outcomes.get(digest(proposal), 'invalid_arguments')
        return {'state': 'clarification' if category == 'missing_info' else 'failed', 'category': category,
                'taskItemId': context.task_item_keys.get(digest(proposal), ''),
                'fieldIssues': context.authorization_details.get(digest(proposal), []),
                'message': reason or '本次操作未执行，请根据失败原因修正参数或说明未完成范围。'}
    if action == 'create_work' and selected and digest(proposal) not in context.title_only_actions:
        from app.modules.work.content.document import WorkDocument, edit_document, plain_text
        effective_body = (edit_document({'schemaVersion': 1, 'content': []}, changes['bodyEdits'])
                          if 'bodyEdits' in changes else WorkDocument.model_validate(changes.get('body') or {}).model_dump())
        if any(item.get('body', '').strip() for item in selected.get('items', [])) and not plain_text(effective_body).strip():
            return {'state': 'failed', 'category': 'invalid_arguments',
                    'fieldIssues': [{'field': 'body', 'code': 'missing'}],
                    'message': '所选方案条目有正文，本次只传标题尚未保存。请在同一步 changes.body 或 bodyEdits 中保留条目目标、内容与条件后重试；不要新建额外副本或设置未要求的下一步/日期。'}
    if action == 'update_work':
        merged = dict(changes)
        for name, addition in context.append_values.get(digest(proposal), {}).items():
            previous = str(proposal.get('targetContent', {}).get(name) or '')
            separator = '\n' if previous and not previous.endswith('\n') else ''
            merged[name] = previous + separator + addition
        changes = merged
        params = {**params, 'changes': changes}
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        prior = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == job.target_id, ((BusinessAction.step == step) | (BusinessAction.intent_key == intent_key) | (BusinessAction.digest == fingerprint))))
        if prior:
            return await receipt(context, db, actor, job, prior) if same_request(prior, action, request_params, fingerprint) else {'state': 'conflict', 'message': '操作内容已变化'}
        if action == 'update_work':
            # Authorization can outlive a concurrent edit. Lock and recheck
            # before reserving a receipt/step so the ordinary refresh gate can
            # recover this unwritten attempt after a fresh read.
            version(await read_target(db, actor, action, target_id), expected_revision)
        message = await owned(db, Message, job.target_id, actor, lock=True)
        task_id = context.task_snapshot.get('taskId', message.id)
        task_item_key = context.task_item_keys.get(digest(proposal), intent_key)
        saved = await db.scalar(select(BusinessAction).where(BusinessAction.task_id == task_id, BusinessAction.task_item_key == task_item_key, BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id).with_for_update())
        if saved:
            previous = context.task_snapshot.get('previousTask', {})
            resumed_cancelled = (saved.state == 'cancelled' and context.task_snapshot.get('relation') == 'continue'
                                 and previous.get('state') == 'cancelled' and previous.get('id') == saved.task_id)
            if saved.message_id == message.id or saved.state not in ('failed', 'conflict') and not resumed_cancelled:
                return await receipt(context, db, actor, job, saved)
            # A new authorized user turn may retry an attempt that never wrote.
            # Keep its historical receipt, but release the unique execution slot
            # after fresh target reads and intent authorization have passed.
            saved.result = {**saved.result, 'originalTaskItemId': saved.task_item_key}
            saved.task_item_key = None
            await db.flush()
        from app.modules.operations.policy.execution_policy import mode_for, decide
        mode = await mode_for(db, job)
        decision = decide(mode, action, changes=changes, explicitly_confirm=digest(proposal) in context.explicit_confirmations)
        row = BusinessAction(execution_mode=mode, mode_revision=job.result.get('modeRevision', 1), approval_reason=decision.reason, company_id=actor.company_id, owner_id=actor.id, message_id=message.id, conversation_id=message.conversation_id, step=step, action=action, task_id=task_id, task_item_key=task_item_key, digest=fingerprint, intent_key=intent_key, params={**params, 'explicitConfirmation': digest(proposal) in context.explicit_confirmations, 'sourceRevision': message.transcript_revision, 'documents': context.document_versions, 'taskSources': [*context.task_snapshot.get('directives', []), *(context.task_snapshot.get('previousTask', {}).get('sources', []) if context.task_snapshot.get('relation') == 'continue' else [])]}, access=job.access or business_scope(actor))
        db.add(row)
        await db.flush()
        try:
            async with db.begin_nested():
                await source_check(db, actor, row)
                if decision.outcome == 'ask':
                    value = await preview(db, actor, row)
                    row.result = {'previewDigest': digest(value), 'objectType': 'work' if action.endswith('work') else 'report', 'objectId': target_id}
                    row.state = 'pending'
                else:
                    await perform(db, actor, row, job, settings=context.settings)
                    if action.startswith('delete_') and row.state == 'succeeded':
                        context.context_sources = {}
                        context.read_versions.pop(target_id, None)
        except HTTPException as error:
            row.state = 'conflict' if error.status_code == 409 else 'failed'
            row.params = {}
            row.result = {'message': error.detail['message']}
        if step == 1 and digest(proposal) in context.receipt_candidates and row.state in ('succeeded', 'pending', 'running'):
            row.result = {**row.result, 'receiptOnly': True, 'receiptInput': digest({'text': request_text(message, job), 'sourceRevision': message.transcript_revision, 'documents': context.document_versions})}
        await db.flush()
        result = await receipt(context, db, actor, job, row)
        from app.tasks.feedback.items import record
        record(job, task_item_key, result)
        return result
