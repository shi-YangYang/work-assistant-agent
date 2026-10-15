"""Retire draft uploads under the same company/attachment locks as binding."""
from sqlalchemy import select
from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.work.models import WorkMaterial
from app.security.locks import company_lock


async def work_reference(db, identifier):
    return await db.scalar(select(WorkMaterial.id).where(
        (WorkMaterial.attachment_id == identifier) |
        (WorkMaterial.source['attachmentId'].astext == identifier),
    ).limit(1))


async def retire_upload(db, actor, identifier):
    await company_lock(db, actor.company_id)
    item = await db.scalar(select(Attachment).where(
        Attachment.id == identifier, Attachment.owner_id == actor.id,
        Attachment.company_id == actor.company_id,
    ).with_for_update().execution_options(populate_existing=True))
    if item is None:
        problem(404, '附件不存在或无权访问')
    if item.deleted:
        return item
    if item.message_id or await work_reference(db, identifier):
        problem(409, '附件已发送或已保存为工作材料，不能从草稿删除')
    item.deleted = True
    item.extraction_status = 'deleted'
    item.extraction_info = {'cleanup_pending': True}
    return item


async def retire_expired_uploads(db, cutoff):
    candidates = (await db.execute(select(Attachment.id, Attachment.company_id).where(
        Attachment.deleted.is_(False), Attachment.message_id.is_(None),
        Attachment.created_at < cutoff,
        ~Attachment.id.in_(select(WorkMaterial.attachment_id)),
        ~Attachment.id.in_(select(WorkMaterial.source['attachmentId'].astext).where(
            WorkMaterial.source['attachmentId'].astext.is_not(None),
        )),
    ).order_by(Attachment.company_id, Attachment.id))).all()
    for identifier, company_id in candidates:
        # Binding takes company -> attachment locks. Candidate snapshots alone
        # cannot protect a source: binding only inserts a clone and WorkMaterial.
        await company_lock(db, company_id)
        item = await db.scalar(select(Attachment).where(
            Attachment.id == identifier, Attachment.company_id == company_id,
            Attachment.deleted.is_(False), Attachment.message_id.is_(None),
            Attachment.created_at < cutoff,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if item is None or await work_reference(db, identifier):
            continue
        item.deleted = True
        item.extraction_status = 'deleted'
        item.extraction_info = {'cleanup_pending': True}


def clean_retired_upload(item, settings):
    from app.integrations.media import remove_media
    try:
        remove_media(settings, item.id)
    except OSError:
        item.extraction_info = {**(item.extraction_info or {}), 'cleanup_pending': True}
        return False
    if (item.extraction_info or {}).get('cleanup_pending'):
        item.extraction_info = {**item.extraction_info, 'cleanup_pending': False}
    return True
