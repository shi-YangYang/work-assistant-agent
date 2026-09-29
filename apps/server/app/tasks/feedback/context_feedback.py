"""Safe usage projection; raw context is never part of a public DTO."""
from app.agent.context.context_usage import THRESHOLD, capacity
from app.db.base import now
from app.tasks.feedback.feedback_state import update_feedback
from app.tasks.lease import lease

FIELDS = {'jobId', 'attempt', 'fence', 'seq', 'model', 'usedTokens', 'contextWindow', 'inputLimit', 'outputReserve', 'capacitySource', 'thresholdRatio', 'estimated', 'state', 'compactionId', 'beforeTokens', 'afterTokens', 'reason', 'updatedAt'}


def usage_dto(job):
    value = (job.result or {}).get('contextUsage')
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in FIELDS if key in value}
    result['seq'] = max(result.get('seq', 0), (job.feedback or {}).get('seq', 0))
    result['updatedAt'] = job.updated_at.isoformat()
    if job.state in ('failed', 'awaiting_retry', 'cancelled'):
        result['state'] = 'failed'
    elif result.get('state') == 'compacting':
        from app.tasks.nodes.node_state import node_dtos
        if any(row['kind'] == 'compaction' and row['state'] == 'retry_wait' for row in node_dtos(job)):
            result['state'] = 'retry_wait'
    return result


async def publish_usage(context, used, *, state='ready', output_reserve=4000, **details):
    cap = capacity(context)
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        if job.kind != 'message':
            return
        previous = job.result.get('contextUsage') or {}
        choice = (context.model_binding or {}).get(context.model_purpose) or {}
        value = {**previous, 'jobId': job.id, 'attempt': job.attempt, 'fence': job.fence,
                 'seq': max(previous.get('seq', 0), (job.feedback or {}).get('seq', 0)) + 1, 'model': choice.get('model', ''),
                 'usedTokens': used, 'contextWindow': cap.get('contextWindow'),
                 'inputLimit': cap.get('inputLimit'), 'outputReserve': output_reserve,
                 'capacitySource': cap.get('source', 'unknown'), 'thresholdRatio': THRESHOLD,
                 'estimated': True, 'state': state, 'updatedAt': now().isoformat(), **details}
        job.result = {**job.result, 'contextUsage': value}
        update_feedback(job)
