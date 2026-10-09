"""Bounded local delivery after execution stops. No new provider or tool call."""
from app.db.base import now
from app.tasks.budget.service import finish as finish_budget
from app.tasks.budget.state import TaskBudgetStopped
from app.tasks.lease import lease


def stopped(error):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, TaskBudgetStopped):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


async def deliver(context, reason):
    from types import SimpleNamespace
    from app.tasks.feedback.reply_stream import temporary_snapshot
    current_job = SimpleNamespace(company_id=context.company_id, owner_id=context.owner_id, id=context.job_id, attempt=context.attempt, fence=context.fence)
    temporary = await temporary_snapshot(context.settings, current_job)
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions, receipt_summary
    from app.modules.deliverables.serializers import delivery_summary
    from app.modules.work.draft_receipts import message_drafts
    from app.modules.conversations.task.task_state import finish
    from app.tasks.feedback.feedback_state import update_feedback
    from app.tasks.feedback.reply_stream import retire
    from app.tasks.feedback.outcomes import derive
    from app.tasks.nodes.node_state import execution, save
    from app.modules.model_services.usage.usage import interrupt_usage
    from app.security.ownership import owned
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor, lock=True)
        safe_text = await safe_prefix(db, actor, job, message, temporary)
        cards = await message_actions(db, actor, message)
        drafts = await message_drafts(db, actor, message, job)
        material = await delivery_summary(db, actor, message)
        receipts = receipt_summary(cards, drafts)
        state = execution(job)
        remaining = list(state.get('budgetBlockedTools', []))
        for row in state.get('nodes', []):
            if row.get('scope') == context.node_scope and row['state'] in ('running', 'retry_wait', 'waiting'):
                remaining.append(row['label'] + '尚未完成')
                row.update(state='failed', nextAt=None, error='此步骤尚未完成', errorCode='stopped', resumable=True)
        remaining = list(dict.fromkeys(remaining))[:8] or ['所需答复尚未整理完成']
        answer = '\n\n'.join(part for part in (safe_text, material, receipts, '本次尚未完成：' + '；'.join(remaining) + '。已保存的结果会保留，你可以继续提出要求。') if part)
        message.reply, message.citations, message.access = answer, [], job.access
        interpretation = {'state': 'blocked', 'remaining': remaining}
        job.state, job.phase, job.error = 'awaiting_input', 'complete', ''
        job.result = {**job.result, 'taskInterpretation': interpretation, 'incompleteTask': True,
                      'conversationReply': answer}
        job.result = {key: value for key, value in job.result.items() if key not in ('pendingReply', 'replyReviewError')}
        if job.result.get('taskBudget'):
            job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'partialDelivered': bool(material or safe_text)}}
        outcome = derive(job, cards, drafts, interpretation=interpretation)
        if (material or safe_text) and outcome['state'] == 'blocked':
            outcome['state'] = 'partial'
        job.result = {**job.result, 'taskOutcome': outcome}
        await finish(db, actor, job, message, interpretation, outcome, delivery_version=2)
        await interrupt_usage(db, job)
        if job.result.get('taskBudget'):
            job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'reason': reason}}
        finish_budget(job)
        save(job, state)
        retire(job)
        update_feedback(job, 'complete', '')
        job.lease_until, job.updated_at = None, now()


async def safe_prefix(db, actor, job, message, temporary):
    from fastapi import HTTPException
    from app.integrations.models.transport import ProviderError
    from app.modules.memories.service import validate_job as validate_memory_job
    from app.tasks.feedback.reply_stream import dto, persist_snapshot, transition
    # The temporary stream may be missing after recovery. Both storage paths
    # must pass the same current-source and memory checks before becoming prose.
    await persist_snapshot(db, actor, job, message, temporary)
    try:
        await validate_memory_job(db, actor, job)
        prefix = await dto(db, actor, job, message)
    except (ValueError, HTTPException, ProviderError):
        transition(job, 'withdrawn')
        return ''
    if not prefix:
        return ''
    if prefix['state'] == 'withdrawn':
        transition(job, 'withdrawn')
    return prefix['text'] if prefix['state'] == 'interrupted' else ''
