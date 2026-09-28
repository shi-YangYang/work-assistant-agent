"""Resolve the image being discussed without crossing conversation boundaries."""
from sqlalchemy import select
from app.core.attachment_limits import MAX_ATTACHMENTS

from app.modules.attachments.models import Attachment
from app.modules.messages.models import Message
from app.modules.messages.service import active_message
from app.security.access import inherit, require, valid


async def referenced_images(db, actor, job, current, attachments):
    if any(item.kind == 'image' for item in attachments):
        return []
    if current.reply_to:
        parent = await active_message(db, current.reply_to, actor)
        if parent.conversation_id != current.conversation_id:
            raise ValueError('回复上下文不属于当前会话')
        await require(db, actor, parent.access)
        candidates = [parent]
    else:
        candidates = (await db.scalars(select(Message).where(
            Message.company_id == actor.company_id, Message.owner_id == actor.id,
            Message.conversation_id == current.conversation_id,
            Message.deleted.is_(False), Message.id != current.id,
            Message.created_at <= current.created_at,
        ).order_by(Message.created_at.desc(), Message.id.desc()).limit(12))).all()
    for parent in candidates:
        if not await valid(db, actor, parent.access):
            continue
        images = list((await db.scalars(select(Attachment).where(
            Attachment.company_id == actor.company_id, Attachment.owner_id == actor.id,
            Attachment.message_id == parent.id, Attachment.deleted.is_(False),
            Attachment.kind == 'image',
        ).order_by(Attachment.created_at, Attachment.id).limit(MAX_ATTACHMENTS))).all())
        if images:
            inherit(actor, job, parent)
            return images
    return []
