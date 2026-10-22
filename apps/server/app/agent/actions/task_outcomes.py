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
    identity = {**{key: proposal.get(key) for key in ('action', 'targetId', 'expectedRevision', 'kind', 'date', 'obligationId', 'sourceTokens')},
                'selection': {key: selected.get(key) for key in ('id', 'revision')} | {'items': sorted(item['id'] for item in selected.get('items', []))}}
    if proposal.get('taskItemId'):
        identity['taskItemId'] = proposal['taskItemId']
    elif proposal['action'] in ('create_work', 'propose_progress', 'propose_followup') and not proposal.get('targetId') and not selected:
        # No object/source exists yet: one incomplete new item must not block a
        # different item. Corrected contents still need independent approval.
        identity['changes'] = proposal.get('changes')
        identity['copyIndex'] = proposal.get('copyIndex', 1)
    return digest(identity)


def slot_key(proposal):
    """A blocked execution slot prevents guessing, never proves success."""
    step = proposal.get('requestStep')
    if not isinstance(step, int):
        return None
    return barrier_key({**proposal, 'taskItemId': f'blocked-slot:{step}'})


def argument_key(proposal):
    return digest({key: value for key, value in proposal.items() if key != 'requestStep'})


def recovery_scope(proposal, item_id=''):
    """Use a checked task item or exact object, never overlapping source files."""
    if item_id or proposal.get('taskItemId'):
        selected = proposal.get('deliverableSelection') or {}
        return {'item': item_id or proposal['taskItemId'],
                'selection': {key: selected.get(key) for key in ('id', 'revision')} |
                             {'items': sorted(item['id'] for item in selected.get('items', []))}}
    if proposal.get('targetId'):
        from app.agent.actions.task_items import work_scope
        return {'kind': proposal['action'], 'target': proposal['targetId'], 'fields': work_scope(proposal)}
    return None


def same_gap(value, proposal):
    issues = value.get('fieldIssues', [])
    from app.agent.actions.work_change_plan import canonical_field
    changes = {canonical_field(name) for name in proposal.get('changes') or {}}
    if issues and all(item.get('code') == 'selection_incomplete' for item in issues):
        from app.agent.actions.material_selection import proposed_sources
        supplied = {digest(source) for source in proposed_sources(proposal)}
        return any(digest(source) not in supplied for item in issues for source in item.get('missingMaterials', []))
    # Removing an unrequested field or supplying a missing one is real parameter
    # correction, even though it is not a new authorization fact.
    if issues and all(item.get('code') == 'not_requested' for item in issues):
        return any(canonical_field(item['field']) in changes for item in issues)
    if issues and all(item.get('code') == 'missing' for item in issues):
        return any(canonical_field(item['field']) not in changes for item in issues)
    return True


def authorization_evidence(request):
    """Fingerprint authorized facts, not timestamps or model-produced state."""
    def unique(values):
        return sorted({digest(value) for value in values})
    reads = request['verifiedReads']
    task = request.get('conversationTask', {})
    return digest({'currentUserText': request['currentUserText'],
        'selectedTarget': task.get('workReference'), 'answers': task.get('interactionAnswers', []),
        'completedOrPendingSteps': unique(request['completedOrPendingSteps']),
        'privateDeliverables': unique([{key: item.get(key) for key in ('id', 'revision', 'latestRevision')}
                                       for item in request['privateDeliverables'].get('items', [])]),
        'verifiedReads': {key: unique(value) if isinstance(value, list) else value for key, value in reads.items()}})


async def blocked(context, proposal, evidence):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        values = job.result.get('taskBarriers', {})
        # An old refusal under a coarse key must not hide a newer exact result.
        value = next((values[key] for key in (barrier_key(proposal), argument_key(proposal), digest(proposal))
                      if key in values and values[key].get('evidence') == evidence), None)
        if not value and not proposal.get('taskItemId'):
            value = values.get(slot_key(proposal))
        if not value:
            item_id = getattr(context, 'task_item_keys', {}).get(digest(proposal), '')
            scope = recovery_scope(proposal, item_id)
            value = next((item for item in reversed(list(values.values()))
                          if scope and item.get('recoveryScope') == scope
                          and item.get('recovery', {}).get('nextAction') in ('ask', 'stop')
                          and item.get('evidence') == evidence and same_gap(item, proposal)), None)
        # New, server-verified facts require a new authorization decision;
        # they never turn a cached refusal into permission. Older barriers
        # without an evidence fingerprint are re-evaluated once as well.
        return value if value and value.get('evidence') == evidence else None


async def barrier(context, proposal, reason, *, evidence, kind='missing_info', recovery=None):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        item_id = getattr(context, 'task_item_keys', {}).get(digest(proposal), proposal.get('taskItemId', ''))
        scope = recovery_scope(proposal, item_id)
        issues = context.authorization_details.get(digest(proposal), [])
        from app.agent.actions.work_change_plan import canonical_field
        gap = digest(sorted({(canonical_field(item.get('field')), item.get('code')) for item in issues}))
        previous = [item for item in job.result.get('taskBarriers', {}).values()
                    if scope and item.get('recoveryScope') == scope and item.get('evidence') == evidence
                    and item.get('gap') == gap]
        attempt = max((item.get('repairAttempts', 0) for item in previous), default=0) + 1
        recovery = dict(recovery or {'owner': 'none' if kind == 'not_requested' else 'assistant',
                                    'missingInputs': [], 'nextAction': 'stop' if kind == 'not_requested' else 'repair',
                                    'code': 'operation_mismatch'})
        if recovery.get('owner') == 'assistant' and attempt >= 2:
            recovery['nextAction'] = 'stop'
        context.authorization_recovery[digest(proposal)] = recovery
        keys = [argument_key(proposal)] if kind in ('invalid_arguments', 'conflict') else [barrier_key(proposal)]
        if kind == 'missing_info':
            if item_id:
                keys.append(barrier_key({**proposal, 'taskItemId': item_id}))
            if slot_key(proposal):
                keys.append(slot_key(proposal))
        value = {'reason': reason[:500], 'category': kind, 'evidence': evidence, 'taskItemId': item_id,
                 'recovery': recovery, 'recoveryScope': scope, 'repairAttempts': attempt,
                 'gap': gap, 'fieldIssues': issues}
        values = {**job.result.get('taskBarriers', {}), **dict.fromkeys(keys, value)}
        job.result = {**job.result, 'taskBarriers': dict(list(values.items())[-32:])}
