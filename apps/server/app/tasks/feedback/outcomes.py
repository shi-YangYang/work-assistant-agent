"""Shared tool outcomes and business completion, independent of queue states."""
from datetime import date, timedelta
from app.core.digests import digest
from app.modules.operations.policy.rules import LABELS

BLOCKING = frozenset({'missing_info', 'permission_denied', 'conflict', 'invalid_arguments', 'transient_failure'})


def category(result):
    if result.get('category'):
        return result['category']
    return {'succeeded': 'success', 'pending': 'confirmation', 'running': 'processing',
        'clarification': 'missing_info', 'waiting': 'missing_info', 'conflict': 'conflict',
        'invalid_reference': 'invalid_arguments', 'not_requested': 'not_requested',
        'failed': 'invalid_arguments', 'cancelled': 'cancelled'}.get(result.get('state'), 'missing_info')


def work_scope(changes):
    scopes = set()
    for name, value in changes.items():
        if name in ('body', 'bodyEdits'):
            scopes.add('body')
        elif name in ('materialIds', 'materials'):
            scopes.add('materials')
        elif name == 'update':
            scopes.add(name + ':' + str(value.get('action', '')) + ':' + str(value.get('id', '')))
        elif name == 'removeMaterial':
            scopes.add(name + ':' + str(value.get('id', '')))
        else:
            scopes.add(name)
    return sorted(scopes)


def record(job, action, arguments, result):
    key = digest({'action': action, **{k: v for k, v in arguments.items() if k not in ('step', 'expected_revision')}})
    reference_fields = ('deliverable_id', 'deliverable_revision', 'item_id')
    effect = digest({'action': action, **{k: v for k, v in arguments.items() if k not in ('step', 'expected_revision', 'task_item_id', *reference_fields)}})
    has_reference = any(arguments.get(name) for name in reference_fields)
    scope = work_scope(arguments.get('changes') or {}) if action in ('update_work', 'edit_report', 'propose_progress', 'propose_followup') else []
    references = {name: arguments.get(name) for name in reference_fields if arguments.get(name)}
    if arguments.get('source_tokens'):
        references['source_tokens'] = sorted(arguments['source_tokens'])
    if arguments.get('copy_index', 1) > 1:
        references['copy_index'] = arguments['copy_index']
    issues = result.get('fieldIssues', [])
    forbidden = {issue['field'] for issue in issues if issue.get('code') == 'not_requested'}
    fields = sorted(({field for field in scope if field.split(':', 1)[0] not in forbidden})
                    | {issue['field'] for issue in issues if issue.get('code') == 'missing'})
    if action == 'create_work':
        fields = []  # A created object fulfills the whole selected item.
    # Report generation captures its sources from the authenticated request on
    # the server. source_tokens is an admin follow-up parameter, not a report
    # selector; correcting it must not invent a different report task. Keep the
    # original references in the receipt, and every other identity boundary.
    identity_references = {name: value for name, value in references.items()
                           if action != 'generate_report' or name != 'source_tokens'}
    identity = {'action': action, 'target': arguments.get('target_id') or '', 'references': identity_references}
    # A create has no object ID yet. Its source item (or exact effect) is the
    # only reliable discriminator; an ordinal or duplicate title is not one.
    if action in ('create_work', 'propose_progress', 'propose_followup') and not arguments.get('target_id') and not has_reference:
        identity['effect'] = effect
    if action == 'generate_report':
        kind, day = arguments.get('report_kind', 'daily'), arguments.get('report_date', '')
        try:
            parsed = date.fromisoformat(day)
            day = (parsed - timedelta(days=parsed.weekday()) if kind == 'weekly' else parsed).isoformat()
        except (TypeError, ValueError):
            pass
        identity['report'] = {'kind': kind, 'period': day, 'obligation': arguments.get('obligation_id') or '',
                              'submitAfter': bool(arguments.get('submit_after'))}
    item = {'identity': digest(identity), 'fields': fields, 'scope': scope, 'key': key, 'action': action, 'category': category(result),
        'taskItemId': arguments.get('task_item_id') or '', 'references': references,
        'state': result.get('state'), 'step': arguments.get('step'), 'effect': effect, 'hasReference': has_reference,
        'target': arguments.get('target_id') or '', 'label': LABELS.get(action, '进展建议'), 'message': str(result.get('message') or '')[:500]}
    if action == 'update_work':
        from app.tasks.feedback.work_requirements import rejected_plan
        rejection = rejected_plan(job, arguments, result)
        if rejection:
            item['planRejection'] = rejection
            key = item['key'] = digest({'operation': key, 'planRejection': rejection})
    if result.get('id') or result.get('draftId'):
        item['receiptId'] = result.get('id') or result['draftId']
    resolved = item['category'] in ('success', 'confirmation', 'processing')
    resolved_keys = {key}
    previous = job.result.get('toolOutcomes', [])
    if action == 'create_work' and has_reference and item['category'] == 'success':
        # The exact same operation may add a validated private-plan reference
        # while correcting its prerequisite. A changed step must not leave the
        # replaced failure visible; different contents or prior links remain.
        resolved_keys.update(entry['key'] for entry in previous
                             if same_item(entry, item) and entry.get('effect') == effect and entry.get('hasReference') is False
                             and entry['category'] in BLOCKING)
    if resolved:
        resolved_keys.update(entry['key'] for entry in previous
            if same_item(entry, item) and not entry.get('planRejection')
            and entry.get('identity') == item['identity'] and entry.get('fields') == item['fields']
            and entry['category'] in BLOCKING)
        if item['taskItemId']:
            resolved_keys.update(entry['key'] for entry in previous
                if not entry.get('planRejection') and entry.get('taskItemId') == item['taskItemId'] and entry.get('action') == action
                and entry.get('target') == item['target'] and entry.get('fields') == item['fields']
                and (action != 'generate_report' or entry.get('identity') == item['identity'])
                and (not entry.get('references') or entry['references'] == references)
                and entry['category'] in BLOCKING)
    values = [entry for entry in previous if entry['key'] not in resolved_keys]
    values.append(item)
    save(job, values[-32:])
    return resolved_keys if resolved else set()


def same_item(previous, current):
    return not previous.get('taskItemId') or not current.get('taskItemId') or previous['taskItemId'] == current['taskItemId']


def reconcile(job, cards):
    from app.tasks.feedback.work_requirements import resolved_rejections
    resolved = resolved_rejections(job, cards)
    if resolved:
        save(job, [entry for entry in job.result.get('toolOutcomes', []) if entry['key'] not in resolved])


def save(job, values):
    job.result = {**job.result, 'toolOutcomes': values}
    job.result = {**job.result, 'operationFeedback': [
        {'key': entry['key'], **{name: entry[name] for name in ('step', 'action', 'label', 'message')},
         'state': entry.get('state') if entry.get('state') in ('failed', 'conflict', 'clarification', 'waiting') else 'failed'}
        for entry in values if entry['category'] in BLOCKING and isinstance(entry.get('step'), int)]}


def derive(job, cards=(), drafts=(), *, interpretation=None):
    """Cards have already been resolved against live authorized business rows."""
    reconcile(job, cards)
    value = interpretation or job.result.get('taskInterpretation', {})
    from app.tasks.feedback.work_requirements import task_with_remaining
    value = task_with_remaining(job, cards, value)
    completed = ['已交付部分内容'] if job.result.get('taskBudget', {}).get('partialDelivered') else []
    remaining = list(value.get('remaining', [])) if value.get('state') not in ('needs_confirmation', 'processing') else []
    pending = running = cancelled = generation_failed = generation_cancelled = False
    for card in cards:
        state = card['state']
        label = card.get('label', '业务操作') + (f"《{card['title']}》" if card.get('title') else '')
        if state == 'succeeded':
            completed.append(label)
        elif state == 'cancelled':
            cancelled = True
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
    # Only the server interaction path owns this phase/ID. A model's textual
    # needs_input cannot turn a permission failure into a request for consent.
    answerable_question = (job.state == 'awaiting_input' and getattr(job, 'phase', '') == 'awaiting_answer'
                           and bool(job.result.get('waitingInteractionId')))
    answerable_failure = answerable_question or any(item['category'] == 'missing_info' for item in failures)
    cannot_resolve_by_reply = not answerable_failure and (response_incomplete or value.get('state') == 'blocked' or any(item['category'] != 'missing_info' for item in failures))
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
    elif cancelled and not completed:
        state, next_action = 'cancelled', 'none'
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
