"""Shared tool outcomes and business completion, independent of queue states."""
from app.core.digests import digest
from app.modules.operations.rules import LABELS

BLOCKING = frozenset({'missing_info', 'permission_denied', 'conflict', 'invalid_arguments', 'transient_failure'})


def category(result):
    if result.get('category'):
        return result['category']
    return {'succeeded': 'success', 'pending': 'confirmation', 'running': 'processing',
        'clarification': 'missing_info', 'waiting': 'missing_info', 'conflict': 'conflict',
        'invalid_reference': 'invalid_arguments', 'not_requested': 'not_requested',
        'failed': 'invalid_arguments', 'cancelled': 'cancelled'}.get(result.get('state'), 'missing_info')


def record(job, action, arguments, result):
    key = digest({'action': action, **{k: v for k, v in arguments.items() if k not in ('step', 'expected_revision')}})
    item = {'key': key, 'action': action, 'category': category(result),
        'step': arguments.get('step'), 'target': arguments.get('target_id') or '', 'label': LABELS.get(action, '进展建议'), 'message': str(result.get('message') or '')[:500]}
    if result.get('id') or result.get('draftId'):
        item['receiptId'] = result.get('id') or result['draftId']
    resolved = item['category'] in ('success', 'confirmation', 'processing')
    values = [entry for entry in job.result.get('toolOutcomes', []) if entry['key'] != key and not (resolved and entry['action'] == action and entry.get('target') == item['target'] and entry.get('step') == item['step'] and entry['category'] in BLOCKING)]
    values.append(item)
    job.result = {**job.result, 'toolOutcomes': values[-32:]}


def derive(job, cards=(), drafts=(), *, interpretation=None):
    """Cards have already been resolved against live authorized business rows."""
    value = interpretation or job.result.get('taskInterpretation', {})
    completed = []
    remaining = list(value.get('remaining', [])) if value.get('state') not in ('needs_confirmation', 'processing') else []
    pending = running = generation_failed = generation_cancelled = False
    for card in cards:
        state = card['state']
        label = card.get('label', '业务操作') + (f"《{card['title']}》" if card.get('title') else '')
        if state == 'succeeded':
            completed.append(label)
        elif state == 'pending':
            pending = True
            remaining.append(label + '等待确认')
        elif state == 'running' and (card.get('job') or {}).get('state') not in ('failed', 'awaiting_retry', 'cancelled'):
            running = True
            remaining.append(label + '处理中')
        else:
            if (card.get('job') or {}).get('state') in ('failed', 'awaiting_retry'):
                generation_failed = True
            if (card.get('job') or {}).get('state') == 'cancelled':
                generation_cancelled = True
            remaining.append(card.get('message') or label + '未完成')
    for draft in drafts:
        if draft.status == 'pending':
            pending = True
            remaining.append('进展建议等待确认')
        elif draft.status == 'confirmed':
            completed.append('进展建议已确认')
    failures = [item for item in job.result.get('toolOutcomes', []) if item['category'] in BLOCKING]
    remaining.extend(item['message'] or item['label'] + '未完成' for item in failures)
    if job.result.get('incompleteTask') and not remaining:
        remaining.append('还有请求的事项尚未完成')
    reason = next((item['message'] for item in failures if item['message']), '')
    response_incomplete = job.result.get('completionIssue') == 'response'
    cannot_resolve_by_reply = response_incomplete or value.get('state') == 'blocked' or any(item['category'] == 'permission_denied' for item in failures)
    if cannot_resolve_by_reply and not reason:
        reason = '必要答复尚未完成核对，已保存的操作结果会保留。' if response_incomplete else next(iter(remaining), '当前权限或条件无法完成此任务。')
    if job.state in ('queued', 'running'):
        state, next_action = 'processing', 'none'
    elif job.state == 'cancelled':
        state, next_action = 'cancelled', 'none'
    elif job.state in ('failed', 'awaiting_retry'):
        state, next_action, reason = 'blocked', 'retry', job.error
    elif generation_failed or generation_cancelled:
        state, next_action = ('partial' if completed else 'blocked' if generation_failed else 'cancelled'), 'none'
        reason = '报告生成未完成，请在报告卡片查看原因或重试。' if generation_failed else '报告生成已中断。'
    elif failures or remaining and not pending and not running:
        state = 'partial' if completed else 'blocked' if cannot_resolve_by_reply else 'needs_input'
        next_action = 'none' if cannot_resolve_by_reply else 'reply'
    elif pending:
        state, next_action = ('partial' if completed else 'needs_confirmation'), 'confirm'
    elif running:
        state, next_action = 'processing', 'none'
    elif value.get('state') == 'blocked':
        state, next_action = ('partial' if completed else 'blocked'), 'none'
    else:
        state, next_action = 'completed', 'none'
    return {'state': state, 'completed': list(dict.fromkeys(completed)),
        'remaining': list(dict.fromkeys(remaining))[:16], 'reason': reason[:500], 'nextAction': next_action}


def dto(job):
    value = job.result.get('taskOutcome')
    if not value:
        return None
    if job.state in ('queued', 'running', 'cancelled', 'failed', 'awaiting_retry'):
        return derive(job)
    return value


def refresh(job, cards=(), drafts=()):
    if job.result.get('taskSnapshot') or job.result.get('taskOutcome'):
        job.result = {**job.result, 'taskOutcome': derive(job, cards, drafts)}
