"""Resolve durable waiting nodes when the actual human decision is committed."""
import json
from sqlalchemy import select
from app.db.base import now
from app.modules.interactions.models import AssistantInteraction
from app.modules.operations.models import BusinessAction
from app.tasks.models import Job
from app.tasks.nodes.node_state import execution, save
from app.tasks.feedback.feedback_state import update_feedback


def node_reference(node):
    output = node.get('output', {})
    try:
        value = json.loads(output.get('content', '{}')) if isinstance(output, dict) else {}
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


async def settle(db, actor, message_id):
    job = await db.scalar(select(Job).where(Job.target_id == message_id, Job.kind == 'message',
        Job.owner_id == actor.id, Job.company_id == actor.company_id).with_for_update())
    if not job:
        return
    questions = (await db.scalars(select(AssistantInteraction).where(AssistantInteraction.message_id == message_id,
        AssistantInteraction.owner_id == actor.id, AssistantInteraction.company_id == actor.company_id))).all()
    actions = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == message_id,
        BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id))).all()
    qstates, astates = {row.id: row.state for row in questions}, {row.id: row.state for row in actions}
    state = execution(job)
    resolved_requests = {}
    for node in state.get('nodes', []):
        value = astates.get(node.get('receiptId') or node_reference(node).get('id'))
        if node.get('scope') == state.get('scope') and node.get('requestKey') and value in ('succeeded', 'running', 'cancelled'):
            resolved_requests[node['requestKey']] = value
    changed = False
    for node in state.get('nodes', []):
        if node.get('scope') != state.get('scope') or node['state'] not in ('awaiting_input', 'awaiting_confirmation'):
            continue
        reference = node_reference(node)
        value = qstates.get(reference.get('interactionId')) if reference.get('interactionId') else astates.get(node.get('receiptId') or reference.get('id'))
        repaired = value is None and bool(node.get('requestKey')) and node['requestKey'] in resolved_requests
        if repaired:
            value = resolved_requests[node['requestKey']]
        if value in ('answered', 'succeeded', 'running', 'cancelled', 'expired'):
            node.update(state='failed' if repaired else 'succeeded' if value in ('answered', 'succeeded', 'running') else 'cancelled',
                error='此前尝试未执行，已由后续步骤处理' if repaired else '', errorCode='superseded' if repaired else '', nextAt=None, resumable=False)
            changed = True
    if changed:
        save(job, state)
    unresolved_node = any(node.get('scope') == state.get('scope') and node['state'] in ('awaiting_input', 'awaiting_confirmation') for node in state.get('nodes', []))
    if unresolved_node or any(row.state == 'waiting' for row in questions) or any(row.state == 'pending' for row in actions):
        return
    if job.state == 'awaiting_input' and job.phase in ('awaiting_answer', 'awaiting_confirmation'):
        cancelled = bool(questions) and all(row.state in ('cancelled', 'expired') for row in questions)
        job.state, job.phase, job.error = ('cancelled', 'cancelled', '') if cancelled else ('succeeded', 'complete', '')
        job.lease_until, job.updated_at = None, now()
        job.result = {**job.result, 'taskInterpretation': {**job.result.get('taskInterpretation', {}), 'state': 'completed', 'remaining': []}}
    from app.tasks.feedback.outcomes import derive
    from app.modules.operations.policy.rules import LABELS
    cards = [{'state': row.state, 'label': LABELS[row.action]} for row in actions]
    job.result = {**job.result, 'taskOutcome': derive(job, cards)}
    update_feedback(job, 'complete' if job.state in ('succeeded', 'cancelled') else None, '')
