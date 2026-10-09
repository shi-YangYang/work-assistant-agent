"""Persist normalized tool feedback and per-run obstruction barriers."""
from app.core.digests import digest
from app.tasks.feedback.outcomes import record


async def remember(context, action, arguments, result):
    from app.tasks.lease import lease
    from app.tasks.feedback.feedback_state import update_feedback
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        resolved_keys = record(job, action, arguments, result)
        update_feedback(job, 'operating', '')
        return resolved_keys



def barrier_key(proposal):
    # Rephrasing values or changing tool call IDs is not new evidence. Object
    # revisions and actual source tokens are; argument errors use exact keys.
    selected = proposal.get('deliverableSelection') or {}
    return digest({**{key: proposal.get(key) for key in ('action', 'targetId', 'expectedRevision', 'kind', 'date', 'sourceTokens')},
                   'selection': {key: selected.get(key) for key in ('id', 'revision')} | {'items': sorted(item['id'] for item in selected.get('items', []))}})


def authorization_evidence(request):
    """Fingerprint authorized facts, not timestamps or model-produced state."""
    def unique(values):
        return sorted({digest(value) for value in values})
    reads = request['verifiedReads']
    return digest({'currentUserText': request['currentUserText'],
        'completedOrPendingSteps': unique(request['completedOrPendingSteps']),
        'privateDeliverables': unique([{key: item.get(key) for key in ('id', 'revision', 'latestRevision')}
                                       for item in request['privateDeliverables'].get('items', [])]),
        'verifiedReads': {key: unique(value) if isinstance(value, list) else value for key, value in reads.items()}})


async def blocked(context, proposal, evidence):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        values = job.result.get('taskBarriers', {})
        value = values.get(barrier_key(proposal)) or values.get(digest(proposal))
        # New, server-verified facts require a new authorization decision;
        # they never turn a cached refusal into permission. Older barriers
        # without an evidence fingerprint are re-evaluated once as well.
        return value if value and value.get('evidence') == evidence else None


async def barrier(context, proposal, reason, *, evidence, kind='missing_info'):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        key = digest(proposal) if kind in ('invalid_arguments', 'conflict') else barrier_key(proposal)
        values = {**job.result.get('taskBarriers', {}), key: {'reason': reason[:500], 'category': kind, 'evidence': evidence}}
        job.result = {**job.result, 'taskBarriers': dict(list(values.items())[-32:])}
