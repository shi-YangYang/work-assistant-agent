"""Local completion of independently extracted work fields, never authorization."""
from copy import deepcopy
LABELS = {'title': '标题', 'summary': '工作说明', 'status': '状态', 'blocker': '阻碍',
          'nextStep': '下一步', 'dueDate': '截止日期', 'body': '工作正文', 'update': '进展记录',
          'materials': '材料', 'removeMaterial': '移除材料'}


def remember(job, *, scope, target, revision, title, fields, previous_receipts, definitions=None):
    state = job.result.get('workChangeRequirements', {})
    if state.get('version') != 1 or state.get('scope') != scope:
        state = {'version': 1, 'scope': scope, 'messageId': job.target_id, 'targets': {}}
    targets = dict(state['targets'])
    previous = targets.get(target, {})
    if previous.get('revision', 0) > revision:
        return  # A late plan from an older read cannot replace the newer scope.
    old_fields = previous.get('fields', {})
    # Replace the latest plan, retaining the baseline only for continuing fields.
    # A corrected preserve decision must remove an erroneous old requirement.
    definitions = definitions or {}
    outcomes = []
    for entry in job.result.get('toolOutcomes', []):
        rejection = entry.get('planRejection')
        if (rejection and rejection['scope'] == scope and rejection['messageId'] == job.target_id
                and rejection['target'] == target
                and any(not compatible_definitions(rejection, values)
                        for values in (previous.get('definitions', {}), definitions))):
            # Retain the observed source/plan conflict across later omissions.
            # Old receipts cannot prove this rejected plan after a source switch.
            entry = {**entry, 'planRejection': {**rejection, 'incompatible': True}}
        outcomes.append(entry)
    targets[target] = {'revision': revision, 'title': title, 'definitions': definitions, 'fields': {
        name: old_fields[name] if name in old_fields and previous.get('definitions', {}).get(name) == definitions.get(name)
        else {'revision': revision, 'excludedReceipts': previous_receipts}
        for name in fields}}
    job.result = {**job.result, 'workChangeRequirements': {**state, 'targets': targets}, 'toolOutcomes': outcomes}


def remaining(job, cards, *, include_pending=False):
    state = job.result.get('workChangeRequirements', {})
    if state.get('version') != 1 or state.get('messageId') != job.target_id:
        return []
    result = []
    for target, requirement in state['targets'].items():
        outstanding = uncovered(job, target, requirement, cards, include_pending=include_pending)
        if outstanding:
            result.append({'targetId': target, 'title': requirement['title'], 'fields': sorted(outstanding)})
    return result


def uncovered(job, target, requirement, cards, *, include_pending=False):
    items = {item['id']: item for item in job.result.get('taskItems', [])}
    outstanding = set(requirement['fields'])
    for card in cards:
        if card.get('action') != 'update_work' or card.get('messageId') != job.target_id:
            continue
        if card['state'] == 'succeeded':
            identifier, revision = card.get('objectId'), card.get('objectRevision', 0)
            fields = set(card.get('changedFields', []))
        elif include_pending and card['state'] == 'pending' and card.get('canConfirm'):
            identifier = items.get(card.get('taskItemId'), {}).get('targetId')
            revision = card['preview']['revision']
            fields = set(card['preview']['changes'])
        else:
            continue
        if identifier != target:
            continue
        fields = {'body' if field == 'bodyEdits' else 'materials' if field == 'materialIds' else field for field in fields}
        if 'summary' in fields and 'update' in requirement['fields']:
            fields.add('update')
        outstanding -= {name for name in fields & outstanding
            if isinstance(revision, int) and revision >= requirement['fields'][name]['revision']
            and card['id'] not in requirement['fields'][name]['excludedReceipts']}
    return outstanding


def rejected_plan(job, arguments, result):
    """Only the independent plan's unwritten extra-field rejection is recoverable."""
    state = job.result.get('workChangeRequirements', {})
    requirement = state.get('targets', {}).get(arguments.get('target_id'))
    forbidden = {issue['field'] for issue in result.get('fieldIssues', []) if issue.get('code') == 'not_requested'}
    if (result.get('state') != 'failed' or result.get('category') != 'invalid_arguments'
            or result.get('id') or result.get('taskItemId') or not forbidden
            or not requirement or not requirement.get('definitions') or not requirement['fields']
            or state.get('messageId') != job.target_id
            or requirement['revision'] != arguments.get('expected_revision')
            or forbidden & requirement['definitions'].keys()):
        return None
    return deepcopy({'scope': state['scope'], 'messageId': state['messageId'], 'target': arguments['target_id'],
                     'requirement': requirement, 'forbidden': sorted(forbidden)})


def resolved_rejections(job, cards):
    """Discard an obsolete proposal only when its original validated plan is saved."""
    state = job.result.get('workChangeRequirements', {})
    resolved = set()
    for entry in job.result.get('toolOutcomes', []):
        rejection = entry.get('planRejection')
        if not rejection or rejection['scope'] != state.get('scope') or rejection['messageId'] != job.target_id:
            continue
        original = rejection['requirement']
        current = state.get('targets', {}).get(rejection['target'], {})
        if (not current or rejection.get('incompatible')
                or not compatible_definitions(rejection, current.get('definitions', {}))):
            continue
        # A newer extraction may omit already-saved fields. It cannot replace
        # their original user sources or use another plan to erase a failure.
        if not uncovered(job, rejection['target'], original, cards):
            resolved.add(entry['key'])
    return resolved


def compatible_definitions(rejection, definitions):
    return (not set(rejection['forbidden']) & definitions.keys()
            and all(rejection['requirement']['definitions'].get(name) == value for name, value in definitions.items()))


def descriptions(values):
    return [f"《{item['title']}》尚未保存：" + '、'.join(LABELS[name] for name in item['fields']) for item in values]


def task_with_remaining(job, cards, task):
    missing = descriptions(remaining(job, cards, include_pending=True))
    if not missing:
        return task
    values = list(dict.fromkeys([*task.get('remaining', []), *missing]))
    return {**task, 'state': 'blocked', 'remaining': values[:7] + ['；'.join(values[7:])] if len(values) > 8 else values}


async def settled_receipt(db, actor, row):
    """Waiting lifecycle needs coverage, without importing the execution stack."""
    from app.modules.work.models import WorkItem
    from app.modules.operations.policy.rules import LABELS as ACTION_LABELS
    from app.security.access import valid
    card = {'id': row.id, 'messageId': row.message_id, 'action': row.action,
            'state': row.state, 'label': ACTION_LABELS[row.action]}
    if row.action != 'update_work' or row.state != 'succeeded':
        return card
    work = await db.get(WorkItem, row.result.get('objectId'))
    if (row.owner_id != actor.id or row.company_id != actor.company_id
            or row.access.get('role') != actor.role or not await valid(db, actor, row.access)
            or not work or work.deleted or work.owner_id != actor.id or work.company_id != actor.company_id
            or not await valid(db, actor, work.access, retained=True)):
        return {**card, 'state': 'unavailable'}
    return {**card, 'objectId': work.id, 'objectRevision': row.result.get('revision'),
            'changedFields': row.result.get('changedFields', [])}
