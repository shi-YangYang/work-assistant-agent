"""Bounded node state stored with its owning job, cleaned up with that job."""
import copy
from datetime import datetime, timezone
from app.tasks.feedback_state import update_feedback

MAX_NODES = 96
MAX_OUTPUT_BYTES = 512_000


def execution(job):
    return copy.deepcopy(job.result.get('nodeExecution', {}))


def save(job, state):
    job.result = {**job.result, 'nodeExecution': state}
    update_feedback(job)


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def node_dtos(job):
    state = job.result.get('nodeExecution', {})
    rows = state.get('nodes', [])
    # Only the active input/configuration scope is rendered. Old bounded summary
    # rows remain for retry accounting but may describe invalidated input.
    result = []
    for row in rows:
        if row.get('scope') != state.get('scope'):
            continue
        status = row['state']
        if job.state == 'cancelled' and status in ('running', 'retry_wait', 'waiting'):
            status = 'cancelled'
        elif job.state in ('failed', 'awaiting_retry') and status in ('running', 'retry_wait'):
            status = 'failed'
        result.append({
            'id': row['id'], 'parentId': row.get('parentId'), 'kind': row['kind'],
            'label': row['label'], 'state': status, 'attempts': row['attempts'],
            'maxAttempts': 4, 'retries': max(0, row['attempts'] - 1),
            'totalRetries': row.get('totalRetries', 0), 'round': row.get('round', 0),
            'nextRetryAt': iso(row.get('nextAt')) if status == 'retry_wait' else None,
            'errorCode': row.get('errorCode', ''), 'error': row.get('error', ''),
            'canRetry': row.get('resumable', False) and status == 'failed' and job.state in ('failed', 'awaiting_retry'),
        })
    return result


def reopen_failed(job):
    state = execution(job)
    for row in state.get('nodes', []):
        if row['state'] in ('failed', 'cancelled', 'running', 'retry_wait') and row.get('scope') == state.get('scope'):
            # Keep only a bounded round summary, never raw exception logs.
            row['history'] = [*row.get('history', []), {'round': row.get('round', 0), 'attempts': row['attempts'], 'errorCode': row.get('errorCode', '')}][-8:]
            row.update(state='waiting', attempts=0, nextAt=None, error='', errorCode='', round=job.attempt + 1)
    state.pop('deadline', None)
    state['actualCalls'] = state['inputTokens'] = state['outputTokens'] = 0
    if state:
        save(job, state)


def release_outputs(job):
    state = execution(job)
    if state:
        for row in state.get('nodes', []):
            row.pop('output', None)
        save(job, state)
