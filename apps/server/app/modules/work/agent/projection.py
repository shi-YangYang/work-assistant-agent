from fastapi import HTTPException
from app.security.access import receipt, remember, require, resolve


async def work_for_model(db, actor, job, work, *, body_start=0, detail=False):
    from app.modules.work.serializers import work_dto
    await require(db, actor, work.access, retained=True)
    result = work_dto(work, overview=True)
    if detail:
        nodes = work.content.get('body', {}).get('content', [])
        selected, size = [], 0
        import json
        for node in nodes[body_start:]:
            size += len(json.dumps(node, ensure_ascii=False))
            if selected and (len(selected) >= 20 or size > 12000):
                break
            selected.append(node)
        result.update(body={'schemaVersion': 1, 'content': selected}, nextBodyStart=body_start + len(selected) if body_start + len(selected) < len(nodes) else None)
        from app.modules.work.updates.service import update_page
        from app.modules.work.materials.service import material_page
        result['updates'] = await update_page(db, work, limit=3)
        result['materials'] = await material_page(db, actor, work, limit=5)
    else:
        result.update(bodyAvailable=bool(work.content.get('body', {}).get('content')), materialCount=len(work.content.get('materialIds', [])))
    if not work.access.get('team'):
        return result
    # A confirmed follow-up is its owner's independent business fact. After its
    # raw source was deleted, use only that fact, never the previous raw context.
    remember(job, actor, {'type': 'own_work', 'id': work.id, 'ownerId': actor.id, 'version': work.revision})
    related = []
    for link in work.business_links:
        try:
            _, member = await resolve(db, actor, link['evidence'])
            remember(job, actor, receipt('member', member))
            related.append({'type': link['evidence']['type'], 'id': link['evidence']['id'], 'employeeId': member.id, 'employeeName': member.name})
        except HTTPException:
            related.append({'unavailable': True})
    result['relatedBusiness'] = related
    return result
