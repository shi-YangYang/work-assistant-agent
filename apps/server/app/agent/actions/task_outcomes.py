"""Persist normalized tool feedback and per-run obstruction barriers."""
from app.core.digests import digest
from app.tasks.feedback.outcomes import record


async def remember(context, action, arguments, result):
    from app.tasks.lease import lease
    from app.tasks.feedback.feedback_state import update_feedback
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        record(job, action, arguments, result)
        update_feedback(job, 'operating', '')



def barrier_key(proposal):
    # Rephrasing values or changing tool call IDs is not new evidence. Object
    # revisions and actual source tokens are; argument errors use exact keys.
    return digest({key: proposal.get(key) for key in ('action', 'targetId', 'expectedRevision', 'kind', 'date', 'sourceTokens')})


async def blocked(context, proposal):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        values = job.result.get('taskBarriers', {})
        return values.get(barrier_key(proposal)) or values.get(digest(proposal))


async def barrier(context, proposal, reason, *, kind='missing_info'):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        key = digest(proposal) if kind in ('invalid_arguments', 'conflict') else barrier_key(proposal)
        values = {**job.result.get('taskBarriers', {}), key: {'reason': reason[:500], 'category': kind}}
        job.result = {**job.result, 'taskBarriers': dict(list(values.items())[-32:])}

