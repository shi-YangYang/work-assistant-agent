from paa_server.core.errors import problem
from paa_server.core.versions import version
from paa_server.db.base import now
from paa_server.modules.messages.service import active_message
from paa_server.modules.work.models import ProgressDraft, WorkItem, WorkRevision
from paa_server.security.access import inherit as business_inherit, require as business_require, resolve as business_resolve
from paa_server.security.locks import company_lock as business_company_lock
from paa_server.security.ownership import owned


async def confirm_drafts(db, actor, items, ignore=False):
    await business_company_lock(db, actor.company_id)
    drafts = [await owned(db, ProgressDraft, item.id, actor, lock=True) for item in sorted(items, key=lambda i: i.id)]
    for draft, item in zip(drafts, sorted(items, key=lambda i: i.id)):
        message = await active_message(db, draft.message_id, actor)
        await business_require(db, actor, message.access)
        business_inherit(actor, draft, message)
        if draft.work_id:
            work = await owned(db, WorkItem, draft.work_id, actor, lock=True)
            await business_require(db, actor, work.access, retained=True)
            business_inherit(actor, draft, work)
        await business_require(db, actor, draft.access)
        if not ignore:
            for link in draft.business_links:
                await business_resolve(db, actor, link['evidence'], latest=True)
        version(draft, item.expectedRevision)
        if draft.status != 'pending':
            problem(409, '这条建议已经处理')
    result = []
    for draft in drafts:
        if not ignore:
            if draft.work_id:
                work = await owned(db, WorkItem, draft.work_id, actor, lock=True)
                await business_require(db, actor, work.access, retained=True)
                version(work, draft.base_revision)
                work.revision += 1
                work.content = {**work.content, **draft.content}
                work.title = draft.content['title']
                work.updated_at = now()
            else:
                work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=draft.content['title'], content=draft.content)
                db.add(work)
                await db.flush()
                draft.work_id = work.id
            business_inherit(actor, work, draft)
            db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=work.revision, content=work.content, source_ids=[draft.message_id], access=work.access, business_links=work.business_links))
            result.append(work.id)
        draft.status = 'ignored' if ignore else 'confirmed'
        draft.revision += 1
    return result
