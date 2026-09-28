from app.agent.intent import authorize_intent
from app.agent.tools.common import referenced_record
from app.core.digests import digest
from app.modules.work.models import WorkItem
from app.modules.messages.models import Message
from app.modules.operations.execution_policy import decide, mode_for
from app.security.ownership import owned
from app.security.access import require as business_require
from app.tasks.lease import lease
from sqlalchemy import select


async def authorize_suggestion(context, action, content, work_id=None, source_tokens=()):
    from app.agent.task_outcomes import remember
    result = await _authorize_suggestion(context, action, content, work_id, source_tokens)
    if result:
        await remember(context, action, {'target_id': work_id, 'changes': content}, result)
    return result


async def _authorize_suggestion(context, action, content, work_id=None, source_tokens=()):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        request_key = digest([action, content, work_id, sorted(source_tokens)])
        saved = job.result.get('suggestionRequests', {}).get(request_key)
        if saved:
            from app.modules.work.models import ProgressDraft
            draft = await owned(db, ProgressDraft, saved['draftId'], actor)
            await business_require(db, actor, draft.access)
            context.suggestion_items[request_key] = saved['itemId']
            return suggestion_receipt(context, job, action, draft, content, work_id, source_tokens)
        target = await referenced_record(db, WorkItem, work_id, actor) if work_id else None
        if work_id and target is None:
            return {'state': 'invalid_reference', 'message': '工作记录不存在或无权查看。新工作请省略 work_id；关联已有工作请先查询并使用真实工作 ID。'}
        if target:
            await business_require(db, actor, target.access, retained=True)
            if context.read_versions.get(target.id) != target.revision:
                return {'state': 'invalid_reference', 'message': '工作记录尚未读取或已被员工更新，请重新读取并核对后提出建议。'}
        candidates = []
        if target:
            candidates = [{'id': row.id, 'title': row.title, 'summary': row.content.get('summary', '')} for row in (await db.scalars(select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id == actor.id, WorkItem.deleted.is_(False), WorkItem.title == target.title).limit(21))).all()]
        message = await owned(db, Message, job.target_id, actor)
        mode = await mode_for(db, job, message.conversation_id)
        operation = 'update_work' if target else 'create_work'
        changes = {key: value for key, value in content.items() if not target or target.content.get(key) != value}
        proposal = {'action': action, 'operation': operation, 'effect': 'prepare_confirmation' if decide(mode, operation).outcome == 'ask' else 'save', 'changes': changes, 'targetId': work_id or '', 'target': target.title if target else '', 'targetCandidates': candidates, 'sourceTokens': list(source_tokens)}
        if target:
            proposal['targetContent'] = target.content
    allowed, reason = await authorize_intent(context, proposal)
    if allowed:
        key = digest([action, content, work_id, sorted(source_tokens)])
        context.suggestion_items[key] = context.task_item_keys[digest(proposal)]
        changes = dict(content)
        for name, addition in context.append_values.get(digest(proposal), {}).items():
            previous = str(proposal.get('targetContent', {}).get(name) or '')
            changes[name] = previous + ('\n' if previous and not previous.endswith('\n') else '') + addition
        context.suggestion_options[key] = {'changes': changes, 'explicitConfirmation': digest(proposal) in context.explicit_confirmations}
        return None
    return {'state': 'not_requested' if digest(proposal) in context.unrequested_actions else 'clarification', 'category': context.authorization_outcomes.get(digest(proposal), 'missing_info'), 'message': reason or '本次未保存进展；请明确是否要记录到工作中'}


def suggestion_key(context, job, action, content, work_id=None, source_tokens=()):
    item_id = context.suggestion_items[digest([action, content, work_id, sorted(source_tokens)])]
    return f"{context.task_snapshot.get('taskId', job.target_id)}:{item_id}"


def suggestion_receipt(context, job, action, draft, content, work_id=None, source_tokens=()):
    from app.tasks.outcomes import record
    from app.tasks.items import record as record_item
    result = {'draftId': draft.id, 'status': draft.status, 'state': 'pending' if draft.status == 'pending' else 'succeeded' if draft.status == 'confirmed' else 'cancelled'}
    record(job, action, {'target_id': work_id, 'changes': content}, result)
    record_item(job, context.suggestion_items[digest([action, content, work_id, sorted(source_tokens)])], result)
    return result


async def settle_suggestion(context, db, job, actor, message, draft, action, content, work_id=None, source_tokens=()):
    """Tool naming does not decide approval; the active policy and user do."""
    options = context.suggestion_options[digest([action, content, work_id, sorted(source_tokens)])]
    draft.content = options['changes']
    mode = await mode_for(db, job, message.conversation_id)
    decision = decide(mode, 'update_work' if work_id else 'create_work', explicitly_confirm=options['explicitConfirmation'])
    if decision.outcome == 'allow':
        from app.modules.work.progress import apply_draft
        work = await apply_draft(db, actor, draft)
        draft.status = 'confirmed'
        draft.revision += 1
        context.read_versions[work.id] = work.revision
    key = digest([action, content, work_id, sorted(source_tokens)])
    job.result = {**job.result, 'suggestionRequests': {**job.result.get('suggestionRequests', {}),
        key: {'draftId': draft.id, 'itemId': context.suggestion_items[key]}}}
    return {**suggestion_receipt(context, job, action, draft, content, work_id, source_tokens),
            'message': '工作已保存，无需再次确认' if draft.status == 'confirmed' else '等待确认'}
