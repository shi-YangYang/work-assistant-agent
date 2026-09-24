from fastapi import HTTPException
from paa_server.security.access import receipt, remember, require, resolve


async def work_for_model(db, actor, job, work):
    from paa_server.modules.work.serializers import work_dto
    await require(db, actor, work.access, retained=True)
    result = work_dto(work)
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
