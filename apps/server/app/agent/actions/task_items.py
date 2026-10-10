"""Bind a semantically checked operation to a durable atomic task item."""
from uuid import uuid4
from app.core.digests import digest


def work_scope(proposal):
    """Separate atomic work-record steps without treating prose as identity."""
    changes = proposal.get('changes') or {}
    scopes = set()
    for field in changes:
        if field in ('body', 'bodyEdits'):
            scopes.add('body')
        elif field in ('materials', 'materialIds'):
            scopes.add('materials')
        elif field == 'update':
            scopes.add('update:' + str(changes[field].get('action', '')) + ':' + str(changes[field].get('id') or ''))
        elif field == 'removeMaterial':
            scopes.add('removeMaterial:' + str(changes[field].get('id') or ''))
        else:
            scopes.add('properties')
    return sorted(scopes)


def reference_error(previous, item_id, proposal):
    if not item_id:
        return ''
    item = next((item for item in previous if item['id'] == item_id), None)
    recovery = '仅复用操作和对象均匹配的事项 ID；尚未尝试的剩余动作没有 ID 时留空，由服务端首次分配，不要借用其它事项或猜测 ID。'
    if not item:
        return '事项引用不存在。' + recovery
    if item['action'] != proposal['action'] or item.get('targetId', '') != proposal.get('targetId', ''):
        return f"事项 {item_id} 已对应 {item['action']}《{item.get('label', '')}》（对象 {item.get('targetId', '')}），与本次操作或对象不一致。" + recovery
    original = item.get('attemptedOperation', {})
    receipt_bound = item.get('receiptId') and item.get('state') not in ('failed', 'conflict', 'clarification', 'proposed')
    # The omitted first copy is already an operation identity, not a missing
    # source that a later correction may supply.
    if proposal['action'] == 'create_work' and original.get('copyIndex', 1) != proposal.get('copyIndex', 1):
        return '事项引用对应不同副本，不能代替另一项操作。' + recovery
    for field in ('deliverableReference', 'kind', 'date', 'obligationId', 'sourceTokens'):
        # A missing source may be supplied while correcting a failed create;
        # a source already bound to another entry may never be replaced.
        if original.get(field) and original[field] != proposal.get(field):
            return '事项引用对应不同来源、报告周期或副本，不能代替另一项操作。' + recovery
    if proposal['action'] == 'update_work' and 'workScope' in item and item['workScope'] != work_scope(proposal):
        return f"事项 {item_id} 对应不同的工作变更范围，不能用正文、进展或材料的已完成回执代替另一项操作。" + recovery
    if proposal['action'] == 'update_work' and receipt_bound:
        aliases = {'bodyEdits': 'body', 'materialIds': 'materials'}
        original_fields = {aliases.get(name, name) for name in original.get('changes', {})}
        fields = {aliases.get(name, name) for name in proposal.get('changes', {})}
        if not original_fields or original_fields != fields:
            return '事项回执对应不同的实际工作字段，不能代替另一项操作。' + recovery
    if proposal['action'] == 'generate_report' and receipt_bound:
        if 'submitAfter' not in original:
            return '事项回执的报告提交要求无法核对，请先核对原操作回执。' + recovery
        if bool(original['submitAfter']) != bool(proposal.get('submitAfter')):
            return '事项回执对应不同的报告提交要求，不能代替另一项操作。' + recovery
    if proposal['action'] in ('edit_report', 'propose_progress', 'propose_followup') and original.get('changes') and set(original['changes']) != set(proposal.get('changes') or {}):
        return '事项引用对应不同的实际字段，不能代替另一项操作。' + recovery
    return ''


def recovery_candidates(job, proposal):
    """Expose failed attempts to the existing judge, never infer their identity."""
    failures = {entry.get('taskItemId'): entry for entry in job.result.get('toolOutcomes', [])
                if entry.get('taskItemId') and entry.get('category') in ('invalid_arguments', 'conflict', 'transient_failure', 'missing_info')}
    return [{**item, 'failure': {key: failures[item['id']].get(key) for key in ('category', 'message', 'fields')}}
            for item in job.result.get('taskItems', [])
            if item['id'] in failures and not item.get('receiptId')
            and not reference_error([item], item['id'], proposal)][-16:]


async def bind(context, proposal, *, continuing=False, item_id='', new_item=False, source=None):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        current = [dict(item) for item in job.result.get('taskItems', [])]
        previous = [dict(item) for item in job.result.get('taskSnapshot', {}).get('previousTask', {}).get('items', [])] if continuing else []
        missing = [item for item in [*previous, *current]
                   if item['action'] == 'update_work' and ('workScope' not in item or item.get('receiptId') and not item.get('attemptedOperation', {}).get('changes'))
                   or item['action'] == 'generate_report' and item.get('receiptId') and 'submitAfter' not in item.get('attemptedOperation', {})]
        if missing:
            from app.modules.operations.models import BusinessAction
            from sqlalchemy import select
            receipts = {row.id: row for row in (await db.scalars(select(BusinessAction).where(
                BusinessAction.id.in_([item.get('receiptId', '') for item in missing]),
                BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id))).all()}
            for item in missing:
                receipt = receipts.get(item.get('receiptId'))
                if item['action'] == 'generate_report':
                    if receipt and 'submitAfter' in receipt.result:
                        item['attemptedOperation'] = {**item.get('attemptedOperation', {}), 'submitAfter': bool(receipt.result['submitAfter'])}
                    elif receipt and 'submitAfter' in receipt.params:
                        item['attemptedOperation'] = {**item.get('attemptedOperation', {}), 'submitAfter': bool(receipt.params['submitAfter'])}
                    continue
                item.setdefault('workScope', [])
                changes = {}
                if receipt and receipt.action == 'update_work':
                    if receipt.params.get('targetId') == item.get('targetId'):
                        item['workScope'] = work_scope(receipt.params)
                        changes = receipt.params.get('changes') or {}
                    elif receipt.state == 'succeeded' and receipt.result.get('objectId') == item.get('targetId'):
                        # Successful receipts erase params but retain changed
                        # field names. Do not guess missing subrecord targets.
                        fields = receipt.result.get('changedFields', [])
                        changes = dict.fromkeys(fields)
                        if not {'update', 'removeMaterial'} & set(fields):
                            item['workScope'] = work_scope({'changes': changes})
                if changes and not item.get('attemptedOperation', {}).get('changes'):
                    item['attemptedOperation'] = {**item.get('attemptedOperation', {}), 'changes': changes}
            job.result = {**job.result, 'taskItems': current}
            if continuing:
                snapshot = job.result['taskSnapshot']
                job.result = {**job.result, 'taskSnapshot': {**snapshot, 'previousTask': {**snapshot['previousTask'], 'items': previous}}}
        candidates = list({item['id']: item for item in [*previous, *current]}.values())
        error = reference_error(candidates, item_id, proposal)
        if error:
            return error
        item = next((item for item in candidates if item['id'] == item_id), None) if item_id else None
        if not item:
            item = next((item for item in current if item.get('proposal') == digest(proposal)), None)
        if continuing and not item and not new_item:
            matches = [item for item in previous if item['action'] == proposal['action'] and item.get('targetId', '') == proposal.get('targetId', '')]
            if proposal['action'] == 'update_work':
                if any(not item.get('workScope') or item.get('receiptId') and not item.get('attemptedOperation', {}).get('changes') for item in matches):
                    return '历史事项的工作变更范围无法核对，不能据此重做或视为完成；请先核对原操作回执。'
                matches = [item for item in matches if item['workScope'] == work_scope(proposal)]
            if proposal['action'] == 'generate_report' and any(item.get('receiptId') and 'submitAfter' not in item.get('attemptedOperation', {}) for item in matches):
                return '历史事项的报告提交要求无法核对，不能据此重做或视为完成；请先核对原操作回执。'
            matches = [item for item in matches if not reference_error([item], item['id'], proposal)]
            if len(matches) == 1:
                item = matches[0]
            elif matches:
                return '继续处理时请提供准确 task_item_id，区分已经完成和仍待处理的事项。'
        if item:
            error = reference_error([item], item['id'], proposal)
            if error:
                return error
        if not item:
            item = {'id': str(uuid4()), 'action': proposal['action'], 'targetId': proposal.get('targetId', ''),
                    'label': str(proposal.get('target') or proposal.get('changes', {}).get('title') or proposal['action'])[:200], 'state': 'proposed'}
            if proposal['action'] == 'update_work':
                item['workScope'] = work_scope(proposal)
        item = {**item, 'proposal': digest(proposal), 'attemptedOperation': {
            name: proposal[name] for name in ('action', 'targetId', 'changes', 'deliverableReference', 'copyIndex', 'kind', 'date', 'obligationId', 'sourceTokens', 'submitAfter') if name in proposal}}
        if source:
            item['userSource'] = source
        job.result = {**job.result, 'taskItems': [entry for entry in job.result.get('taskItems', []) if entry['id'] != item['id']] + [item]}
        context.task_item_keys[digest(proposal)] = item['id']
        return ''
