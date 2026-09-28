from app.core.errors import problem
from app.core.versions import version
from app.modules.messages.service import active_message
from app.modules.work.models import ProgressDraft, WorkItem
from app.security.access import inherit as business_inherit, require as business_require, resolve as business_resolve
from app.security.locks import company_lock as business_company_lock
from app.security.ownership import owned


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
            work = await apply_draft(db, actor, draft, confirmed=True)
            result.append(work.id)
        draft.status = 'ignored' if ignore else 'confirmed'
        draft.revision += 1
    return result


async def apply_draft(db, actor, draft, *, confirmed=False):
    """Both execution modes and approval publish through the same work writer."""
    from app.modules.work.service import save_work
    work = await save_work(db, actor, draft.content, identifier=draft.work_id,
        expected=draft.base_revision, sources=[draft.message_id],
        origin='suggestion' if confirmed else 'assistant',
        revision_origin='assistant_confirmed' if confirmed else 'assistant',
        links=draft.business_links, access=draft.access)
    draft.work_id = work.id
    return work
