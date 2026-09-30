from app.tasks.nodes.node_state import node_dtos

def job_dto(job):
    from app.tasks.feedback.context_feedback import usage_dto
    from app.tasks.feedback.outcomes import dto as outcome_dto
    return {'taskOutcome': outcome_dto(job), 'contextUsage': usage_dto(job), 'incompleteTask': bool(job.result.get('incompleteTask')), 'nodes': node_dtos(job), 'operationFeedback': job.result.get('operationFeedback', []), 'id': job.id, 'kind': job.kind, 'targetId': job.target_id, 'state': job.state, 'phase': job.phase, 'stage': (job.feedback or {}).get('stage', 'queued'), 'attempt': job.attempt, 'fence': job.fence, 'error': job.error, 'configAttempt': job.config_attempt, 'modelSource': {k: ({'service': v['name'], 'model': v['model'], 'revision': v['revision']} if isinstance(v, dict) and 'model' in v else v) for k, v in (job.model_binding or {}).items() if k in ('assistant', 'report', 'asr', 'source', 'routingRevision')}, 'updatedAt': job.updated_at.isoformat()}
