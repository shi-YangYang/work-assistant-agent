"""Bind a semantically checked operation to a durable atomic task item."""
from uuid import uuid4
from app.core.digests import digest


def reference_error(previous, item_id, proposal):
    if not item_id:
        return ''
    item = next((item for item in previous if item['id'] == item_id), None)
    recovery = '仅复用操作和对象均匹配的事项 ID；尚未尝试的剩余动作没有 ID 时留空，由服务端首次分配，不要借用其它事项或猜测 ID。'
    if not item:
        return '事项引用不存在。' + recovery
    if item['action'] != proposal['action'] or item.get('targetId', '') != proposal.get('targetId', ''):
        return f"事项 {item_id} 已对应 {item['action']}《{item.get('label', '')}》（对象 {item.get('targetId', '')}），与本次操作或对象不一致。" + recovery
    return ''


async def bind(context, proposal, *, continuing=False, item_id='', new_item=False):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        local = next((item for item in job.result.get('taskItems', []) if item.get('proposal') == digest(proposal)), None)
        if local:
            context.task_item_keys[digest(proposal)] = local['id']
            return ''
        previous = job.result.get('taskSnapshot', {}).get('previousTask', {}).get('items', []) if continuing else []
        error = reference_error(previous, item_id, proposal)
        if error:
            return error
        item = next((item for item in previous if item['id'] == item_id), None) if item_id else None
        if continuing and not item and not new_item:
            matches = [item for item in previous if item['action'] == proposal['action'] and item.get('targetId', '') == proposal.get('targetId', '')]
            if len(matches) == 1:
                item = matches[0]
            elif matches:
                return '继续处理时请提供准确 task_item_id，区分已经完成和仍待处理的事项。'
        if not item:
            item = {'id': str(uuid4()), 'action': proposal['action'], 'targetId': proposal.get('targetId', ''),
                    'label': str(proposal.get('target') or proposal.get('changes', {}).get('title') or proposal['action'])[:200], 'state': 'proposed'}
        item = {**item, 'proposal': digest(proposal)}
        job.result = {**job.result, 'taskItems': [entry for entry in job.result.get('taskItems', []) if entry['id'] != item['id']] + [item]}
        context.task_item_keys[digest(proposal)] = item['id']
        return ''
