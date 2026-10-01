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
    if proposal['action'] == 'update_work' and 'workScope' in item and item['workScope'] != work_scope(proposal):
        return f"事项 {item_id} 对应不同的工作变更范围，不能用正文、进展或材料的已完成回执代替另一项操作。" + recovery
    return ''


async def bind(context, proposal, *, continuing=False, item_id='', new_item=False):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        local = next((item for item in job.result.get('taskItems', []) if item.get('proposal') == digest(proposal)), None)
        if local:
            context.task_item_keys[digest(proposal)] = local['id']
            return ''
        previous = [dict(item) for item in job.result.get('taskSnapshot', {}).get('previousTask', {}).get('items', [])] if continuing else []
        missing = [item for item in previous if item['action'] == 'update_work' and 'workScope' not in item]
        if missing:
            from app.modules.operations.models import BusinessAction
            from sqlalchemy import select
            receipts = {row.id: row for row in (await db.scalars(select(BusinessAction).where(
                BusinessAction.id.in_([item.get('receiptId', '') for item in missing]),
                BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id))).all()}
            for item in missing:
                receipt = receipts.get(item.get('receiptId'))
                item['workScope'] = []
                if receipt and receipt.action == 'update_work':
                    if receipt.params.get('targetId') == item.get('targetId'):
                        item['workScope'] = work_scope(receipt.params)
                    elif receipt.state == 'succeeded' and receipt.result.get('objectId') == item.get('targetId'):
                        # Successful receipts erase params but retain changed
                        # field names. Do not guess missing subrecord targets.
                        fields = receipt.result.get('changedFields', [])
                        if not {'update', 'removeMaterial'} & set(fields):
                            item['workScope'] = work_scope({'changes': dict.fromkeys(fields)})
            snapshot = job.result['taskSnapshot']
            job.result = {**job.result, 'taskSnapshot': {**snapshot, 'previousTask': {**snapshot['previousTask'], 'items': previous}}}
        error = reference_error(previous, item_id, proposal)
        if error:
            return error
        item = next((item for item in previous if item['id'] == item_id), None) if item_id else None
        if continuing and not item and not new_item:
            matches = [item for item in previous if item['action'] == proposal['action'] and item.get('targetId', '') == proposal.get('targetId', '')]
            if proposal['action'] == 'update_work':
                if any(not item.get('workScope') for item in matches):
                    return '历史事项的工作变更范围无法核对，不能据此重做或视为完成；请先核对原操作回执。'
                matches = [item for item in matches if item['workScope'] == work_scope(proposal)]
            if len(matches) == 1:
                item = matches[0]
            elif matches:
                return '继续处理时请提供准确 task_item_id，区分已经完成和仍待处理的事项。'
        if not item:
            item = {'id': str(uuid4()), 'action': proposal['action'], 'targetId': proposal.get('targetId', ''),
                    'label': str(proposal.get('target') or proposal.get('changes', {}).get('title') or proposal['action'])[:200], 'state': 'proposed'}
            if proposal['action'] == 'update_work':
                item['workScope'] = work_scope(proposal)
        item = {**item, 'proposal': digest(proposal)}
        job.result = {**job.result, 'taskItems': [entry for entry in job.result.get('taskItems', []) if entry['id'] != item['id']] + [item]}
        context.task_item_keys[digest(proposal)] = item['id']
        return ''
