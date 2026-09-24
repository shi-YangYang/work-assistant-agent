from paa_server.core.errors import problem
from paa_server.core.versions import version
from paa_server.db.base import now
from paa_server.modules.messages.service import active_message
from paa_server.modules.work.models import WorkItem, WorkRevision
from paa_server.modules.work.schemas import Progress
from paa_server.security.access import inherit as business_inherit, merge_access as business_merge_access, merge_links as business_merge_links, require as business_require, scope as business_scope
from paa_server.security.locks import company_lock as business_company_lock
from paa_server.security.ownership import owned


async def save_work(db, actor, patch, *, identifier=None, expected=None, sources=(), origin='manual', links=(), access=None):
    await business_company_lock(db, actor.company_id)
    if identifier:
        work = await owned(db, WorkItem, identifier, actor, lock=True)
        await business_require(db, actor, work.access, retained=True)
        version(work, expected)
        content = Progress.model_validate({**work.content, **patch}).model_dump(mode='json')
    else:
        content = Progress.model_validate(patch).model_dump(mode='json')
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=content['title'], content=content, origin=origin)
        db.add(work)
        await db.flush()
    if not content['title'].strip():
        problem(422, '请填写工作标题')
    for source in sources:
        message = await active_message(db, source, actor)
        await business_require(db, actor, message.access)
        business_inherit(actor, work, message, include_message_links=True)
    if access:
        work.access = business_merge_access(work.access or business_scope(actor), access)
    work.business_links = business_merge_links(work.business_links, list(links))
    if identifier and content == work.content and not links and (not sources or origin == 'assistant'):
        return work
    if identifier:
        work.revision += 1
    work.content, work.title, work.updated_at = content, content['title'], now()
    db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=work.revision, content=content, source_ids=list(sources), access=work.access, business_links=work.business_links))
    await db.flush()
    return work
