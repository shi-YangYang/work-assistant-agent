from app.core.errors import problem
from app.core.versions import version
from app.db.idempotency import idem_begin, idem_save
from app.modules.messages.service import active_message
from app.modules.work.models import ProgressDraft, WorkItem
from app.modules.work.progress import confirm_drafts
from app.modules.work.serializers import draft_dto, work_dto
from app.modules.work.service import save_work as writes_save_work
from app.security.access import inherit as business_inherit, require as business_require
from app.security.ownership import owned


async def create_work_command(body, idempotency_key, actor, db):
    prior, digest = await idem_begin(db, actor, 'create-work', idempotency_key, body.model_dump(mode='json'))
    if prior:
        item = await owned(db, WorkItem, prior['id'], actor)
        await business_require(db, actor, item.access, retained=True)
        return prior
    item = await writes_save_work(db, actor, body.model_dump(mode='json'))
    return idem_save(db, actor, 'create-work', idempotency_key, digest, work_dto(item))


async def edit_draft_command(identifier, body, actor, db):
    draft = await owned(db, ProgressDraft, identifier, actor, lock=True)
    message = await active_message(db, draft.message_id, actor)
    await business_require(db, actor, message.access)
    await business_require(db, actor, draft.access)
    version(draft, body.expectedRevision)
    if draft.status != 'pending':
        problem(409, '建议已处理')
    work = await owned(db, WorkItem, body.workId, actor) if body.workId else None
    if work:
        await business_require(db, actor, work.access, retained=True)
    business_inherit(actor, draft, message, *([work] if work else []))
    draft.work_id, draft.base_revision = (work.id, work.revision) if work else (None, None)
    draft.content = {**draft.content, **body.model_dump(mode='json', exclude={'expectedRevision', 'workId'}, exclude_unset=True)}
    draft.revision += 1
    return draft_dto(draft)


async def process_drafts_command(action, body, idempotency_key, actor, db):
    if action not in ('confirm', 'ignore'):
        problem(404, '操作不存在')
    prior, digest = await idem_begin(db, actor, action, idempotency_key, body.model_dump())
    if prior:
        return prior
    work_ids = await confirm_drafts(db, actor, body.items, ignore=action == 'ignore')
    return idem_save(db, actor, action, idempotency_key, digest, {'workIds': work_ids})
