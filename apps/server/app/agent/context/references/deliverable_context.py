"""Small private-result index, shared by planning and independent authorization."""
from app.modules.deliverables.queries import conversation_deliverables, available_revision, check_reference, remember_source
from app.modules.deliverables.serializers import summary
from app.security.access import valid


async def deliverable_context(db, actor, message, *, job=None):
    if not message.conversation_id:
        return {}
    rows = await conversation_deliverables(db, actor, message.conversation_id)
    result = {'items': [], 'moreAvailable': len(rows) > 20}
    for row in rows[:20]:
        if not await valid(db, actor, row.access):
            continue
        record = await available_revision(db, actor, row.id)
        if record:
            if job is not None:
                remember_source(job, actor, row, record)
            entry = summary(row, record)
            # Carry the exact binding shape once, next to each file; callers
            # must not mistake a deliverable file ID for a WorkMaterial ID.
            for file in entry['files']:
                file['materialSource'] = {'deliverableId': row.id, 'revision': record.revision, 'fileId': file['id']}
            result['items'].append(entry)
    result['fileCount'] = sum(len(item['files']) for item in result['items'])
    result['collectionComplete'] = not result['moreAvailable']
    if message.deliverable_reference:
        item, record = await check_reference(db, actor, message.deliverable_reference, message.conversation_id)
        if job is not None:
            remember_source(job, actor, item, record)
        result['selected'] = {**message.deliverable_reference, 'title': record.title}
    return result
