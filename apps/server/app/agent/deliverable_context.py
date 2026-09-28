"""Small private-result index, shared by planning and independent authorization."""
from app.modules.deliverables.queries import conversation_deliverables, get_deliverable, check_reference
from app.modules.deliverables.serializers import summary
from app.security.access import valid


async def deliverable_context(db, actor, message):
    if not message.conversation_id:
        return {}
    rows = await conversation_deliverables(db, actor, message.conversation_id)
    result = {'items': [], 'moreAvailable': len(rows) > 20}
    for row in rows[:20]:
        if not await valid(db, actor, row.access):
            continue
        _, record = await get_deliverable(db, actor, row.id)
        result['items'].append(summary(row, record))
    if message.deliverable_reference:
        _, record = await check_reference(db, actor, message.deliverable_reference, message.conversation_id)
        result['selected'] = {**message.deliverable_reference, 'title': record.title}
    return result
