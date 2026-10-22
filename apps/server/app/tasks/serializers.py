from app.tasks.nodes.node_state import node_dtos
from app.tasks.feedback.image_feedback import dto as image_dto

def job_dto(job):
    from app.tasks.feedback.context_feedback import usage_dto
    from app.tasks.feedback.outcomes import dto as outcome_dto
    from app.tasks.feedback.public import feedback, job_error
    return {'imageGeneration': image_dto(job), 'taskOutcome': outcome_dto(job), 'contextUsage': usage_dto(job), 'incompleteTask': bool(job.result.get('incompleteTask')), 'nodes': node_dtos(job), 'operationFeedback': feedback(job.result.get('operationFeedback', []), job.result.get('toolOutcomes', [])), 'id': job.id, 'kind': job.kind, 'targetId': job.target_id, 'state': job.state, 'phase': job.phase, 'stage': (job.feedback or {}).get('stage', 'queued'), 'attempt': job.attempt, 'fence': job.fence, 'error': job_error(job), 'configAttempt': job.config_attempt, 'modelSource': {k: ({'service': v['name'], 'model': v['model'], 'revision': v['revision']} if isinstance(v, dict) and 'model' in v else v) for k, v in (job.model_binding or {}).items() if k in ('assistant', 'report', 'asr', 'source', 'routingRevision')}, 'updatedAt': job.updated_at.isoformat()}
