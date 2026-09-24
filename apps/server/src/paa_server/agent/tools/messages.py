from langchain.tools import ToolRuntime, tool
from paa_server.agent.tools.common import clip, referenced_record
from paa_server.modules.attachments.inventory import attachment_inventory
from paa_server.modules.attachments.models import Attachment
from paa_server.modules.messages.models import Message
from paa_server.modules.work.models import ProgressDraft, WorkItem, WorkRevision
from paa_server.security.access import merge_access as business_merge_access, require as business_require, scope as business_scope
from paa_server.security.ownership import owned
from paa_server.tasks.context import RunContext
from paa_server.tasks.lease import lease
from sqlalchemy import select


@tool
async def get_message_context(message_id: str, runtime: ToolRuntime[RunContext]) -> str:
    """Read the authorized message, attachment inventory, corrected transcript and reply."""
    async with runtime.context.sessions.begin() as db:
        _, actor = await lease(db, runtime.context)
        message = await referenced_record(db, Message, message_id, actor)
        if message is None:
            return '消息不存在或无权查看。请使用本次上下文中的原消息 ID，不要猜测 ID。'
        current_job, _ = await lease(db, runtime.context)
        if current_job.kind == 'message':
            current = await owned(db, Message, current_job.target_id, actor)
            if message.conversation_id != current.conversation_id:
                source = await db.scalar(select(WorkRevision.id).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.owner_id == actor.id, WorkItem.deleted.is_(False), WorkRevision.source_ids.contains([message.id])).limit(1))
                if source is None:
                    return '这条消息不属于当前会话或已确认工作来源。'
        await business_require(db, actor, message.access)
        current_job.access = business_merge_access(current_job.access or business_scope(actor), message.access)
        drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == message.id, ProgressDraft.owner_id == actor.id, ProgressDraft.company_id == actor.company_id).order_by(ProgressDraft.created_at.desc()).limit(20))).all()
        attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == message.id, Attachment.deleted.is_(False)).order_by(Attachment.created_at, Attachment.id))).all()
        from paa_server.agent.conversation_context import message_reference
        reference = await message_reference(db, actor, message)
        return clip({'id': message.id, 'attachments': attachment_inventory(attachments, message.transcript, message.transcript_revision), 'progress': [{'status': draft.status, 'workId': draft.work_id} for draft in drafts], 'text': message.text, 'transcript': message.transcript, 'userRequest': reference['userText'], 'reply': reference['assistantReference'], 'replyIsHistorical': True, 'currentActions': reference['currentActions'], 'documents': [{'id': item.id, 'name': item.name, 'status': item.extraction_status} for item in attachments if item.kind == 'document']})
