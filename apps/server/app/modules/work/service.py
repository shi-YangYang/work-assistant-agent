from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.modules.messages.service import active_message
from app.modules.work.models import WorkItem, WorkRevision
from app.modules.work.schemas import Progress
from app.security.access import inherit as business_inherit, merge_access as business_merge_access, merge_links as business_merge_links, require as business_require, scope as business_scope
from app.security.locks import company_lock as business_company_lock
from app.security.ownership import owned


async def save_work(db, actor, patch, *, identifier=None, expected=None, sources=(), origin='manual', links=(), access=None, publication=None, revision_origin=None, legacy_progress=True, force_revision=False):
    await business_company_lock(db, actor.company_id)
    if identifier:
        work = await owned(db, WorkItem, identifier, actor, lock=True)
        await business_require(db, actor, work.access, retained=True)
        version(work, expected)
        merged = {**work.content, **patch}
        content = {**merged, **Progress.model_validate({key: value for key, value in merged.items() if key in Progress.model_fields}).model_dump(mode='json')}
    else:
        content = {**patch, **Progress.model_validate({key: value for key, value in patch.items() if key in Progress.model_fields}).model_dump(mode='json')}
        from app.modules.work.content.document import from_text, plain_text
        content.setdefault('body', from_text(content.get('summary', '')))
        content.setdefault('bodyText', plain_text(content['body']))
        content.setdefault('materialIds', [])
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=content['title'], content=content, origin=origin)
        db.add(work)
        await db.flush()
    if not content['title'].strip():
        problem(422, '请填写工作标题')
    private_sources = []
    public_sources = []
    for source in sources:
        message = await active_message(db, source, actor)
        await business_require(db, actor, message.access)
        (private_sources if message.private_context else public_sources).append(source)
        business_inherit(actor, work, message, include_message_links=True)
    if access:
        work.access = business_merge_access(work.access or business_scope(actor), access)
    work.business_links = business_merge_links(work.business_links, list(links))
    previous_summary = work.content.get('summary', '') if identifier else ''
    new_progress = legacy_progress and 'summary' in patch and patch['summary'].strip() and (not identifier or patch['summary'] != previous_summary)
    attributes_changed = identifier and any(content.get(field) != work.content.get(field) for field in ('title', 'status', 'dueDate', 'blocker', 'nextStep'))
    if identifier and not force_revision and content == work.content and not links and (not sources or origin in ('assistant', 'suggestion')):
        return work
    if identifier:
        work.revision += 1
    work.content, work.title, work.updated_at = content, content['title'], now()
    if publication is None and private_sources:
        from app.modules.operations.mutations.publication import snapshot
        publication = snapshot(content, message_ids=private_sources)
    if publication is not None:
        publication = {**publication, 'content': content}
    # Legacy API and scalar-only agent actions share this writer. Their inherited
    # summary is not new progress, but their attribute changes are report facts.
    revision_content = {**content, '_changeKind': 'properties'} if legacy_progress and attributes_changed and not new_progress else content
    db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=work.revision, origin=revision_origin or origin, content=revision_content, source_ids=public_sources, publication=publication or {}, access=work.access, business_links=work.business_links))
    await db.flush()
    if new_progress:
        from app.modules.work.updates.service import save_update
        await save_update(db, actor, work, patch['summary'], [], revision_origin or origin)
    return work
