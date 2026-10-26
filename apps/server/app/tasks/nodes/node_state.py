"""Bounded node state stored with its owning job, cleaned up with that job."""
import copy
import json
from datetime import datetime, timezone
from app.tasks.feedback.feedback_state import update_feedback

MAX_NODES = 96
MAX_OUTPUT_BYTES = 512_000


def execution(job):
    return copy.deepcopy(job.result.get('nodeExecution', {}))


def save(job, state):
    job.result = {**job.result, 'nodeExecution': state}
    update_feedback(job)


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def business_item(row):
    if row.get('businessTaskItemId'):
        return row['businessTaskItemId']
    output = row.get('output') or {}
    if not isinstance(output, dict) or output.get('name') != 'execute_business_action':
        return None
    try:
        value = json.loads(output.get('content', '{}'))
    except (TypeError, ValueError):
        return None
    return value.get('taskItemId') if isinstance(value, dict) else None


def recovered_business_item(job, row):
    """Display a recovered request without rewriting the failed attempt journal."""
    from app.tasks.feedback.outcomes import BLOCKING
    if row.get('kind') != 'tool' or row.get('state') != 'failed':
        return False
    item_id = business_item(row)
    item = next((item for item in job.result.get('taskItems', []) if item['id'] == item_id), {})
    if item.get('action') not in ('create_work', 'update_work') or item.get('state') != 'succeeded' or not item.get('receiptId'):
        return False
    if any(outcome.get('taskItemId') == item_id and outcome.get('category') in BLOCKING
           for outcome in job.result.get('toolOutcomes', [])):
        return False
    return any(outcome.get('taskItemId') == item_id and outcome.get('action') == item['action']
               and outcome.get('receiptId') == item['receiptId'] and outcome.get('category') == 'success'
               for outcome in job.result.get('toolOutcomes', []))


def node_dtos(job):
    from app.tasks.feedback.public import node_error
    state = job.result.get('nodeExecution', {})
    rows = state.get('nodes', [])
    # Only the active input/configuration scope is rendered. Old bounded summary
    # rows remain for retry accounting but may describe invalidated input.
    result = []
    for row in rows:
        if row.get('scope') != state.get('scope'):
            continue
        recovered = recovered_business_item(job, row)
        status = 'succeeded' if recovered else row['state']
        if job.state == 'cancelled' and status in ('running', 'retry_wait', 'waiting'):
            status = 'cancelled'
        # Retrying can take a different path, leaving reopened nodes unused.
        # Once the task ends, those nodes cannot still be waiting or running.
        elif job.state in ('succeeded', 'awaiting_input', 'failed', 'awaiting_retry') and status in ('running', 'retry_wait', 'waiting'):
            status = 'failed'
        result.append({
            'id': row['id'], 'parentId': row.get('parentId'), 'kind': row['kind'],
            'label': row['label'] + ('（已恢复）' if recovered else ''), 'state': status, 'attempts': row['attempts'],
            **({'presentation': row['presentation']} if row.get('presentation') else {}),
            **({'activity': row['activity']} if row.get('activity') and status == 'running' else {}),
            'maxAttempts': row.get('maxAttempts', 4), 'retries': max(0, row['attempts'] - 1),
            'totalRetries': row.get('totalRetries', 0), 'round': row.get('round', 0),
            'nextRetryAt': iso(row.get('nextAt')) if status == 'retry_wait' else None,
            'errorCode': '' if recovered else row.get('errorCode', ''), 'error': '' if recovered else node_error(row),
            'canRetry': row.get('resumable', False) and status == 'failed' and job.state in ('failed', 'awaiting_retry'),
        })
    return result


def reopen_failed(job):
    from app.tasks.budget.service import reset
    reset(job)
    state = execution(job)
    for row in state.get('nodes', []):
        if row['state'] in ('failed', 'cancelled', 'running', 'retry_wait') and row.get('scope') == state.get('scope'):
            # Keep only a bounded round summary, never raw exception logs.
            row['history'] = [*row.get('history', []), {'round': row.get('round', 0), 'attempts': row['attempts'], 'errorCode': row.get('errorCode', '')}][-8:]
            row.update(state='waiting', attempts=0, nextAt=None, error='', errorCode='', round=job.attempt + 1)
            row.pop('errorCategory', None)
    state.pop('deadline', None)
    state.pop('budgetBlockedTools', None)
    state['actualCalls'] = state['inputTokens'] = state['outputTokens'] = 0
    if state:
        save(job, state)


def cancel_unfinished(job, *, succeeded_receipts=()):
    from app.tasks.budget.service import finish
    finish(job)
    state = execution(job)
    if state:
        for row in state.get('nodes', []):
            if row.get('scope') == state.get('scope') and row['state'] in ('waiting', 'running', 'retry_wait', 'awaiting_input', 'awaiting_confirmation'):
                # A committed business receipt can precede the tool's final
                # journal write. Cancellation stops later work, not that effect.
                committed = row.get('receiptId') in succeeded_receipts
                row.update(state='succeeded' if committed else 'cancelled', nextAt=None,
                           error='' if committed else '已中断', errorCode='' if committed else 'cancelled', resumable=False)
                row.pop('errorCategory', None)
        save(job, state)


def release_outputs(job):
    state = execution(job)
    if state:
        for row in state.get('nodes', []):
            if item_id := business_item(row):
                row['businessTaskItemId'] = item_id
            row.pop('output', None)
        save(job, state)
