from app.core.errors import problem
from app.modules.conversations.models import Conversation, ConversationTaskState
from app.modules.messages.models import Message
from app.modules.interactions.models import AssistantInteraction
from app.security.access import require
from app.security.ownership import owned
from sqlalchemy import select


async def validate(db, actor, row, *, current=False):
    await owned(db, Conversation, row.conversation_id, actor)
    message = await owned(db, Message, row.message_id, actor)
    await require(db, actor, row.access, latest=True)
    if row.access and row.access.get('role') != actor.role:
        problem(409, '账号权限已变化，请重新提问')
    if message.transcript_revision != row.source_revision:
        problem(409, '问题所依据的材料已变化，请重新提问')
    from app.modules.conversations.task.task_state import source_text
    for source in row.sources:
        if await source_text(db, actor, row.conversation_id, source) is None:
            problem(409, '任务来源已变化，该问题已失效')
    for question in row.questions:
        for option in question['options']:
            if option.get('objectId'):
                from app.modules.work.models import WorkItem
                from app.modules.reports.models import Report
                from app.modules.members.models import Member
                model = {'work': WorkItem, 'report': Report, 'member': Member}[option['objectType']]
                if model is Member:
                    from app.security.access import employee
                    await employee(db, actor, option['objectId'])
                else:
                    item = await owned(db, model, option['objectId'], actor, read=True)
                    if option.get('objectRevision') != item.revision:
                        if row.state != 'answered':
                            problem(409, '候选对象已变化，请重新提问')
                        from app.security.versions import receipt_advanced_versions
                        from app.integrations.models.transport import ProviderError
                        try:
                            await receipt_advanced_versions(db, actor, {item.id: option['objectRevision']}, task_id=row.task_id)
                        except ProviderError:
                            problem(409, '候选对象存在外部修改，请重新提问')
                    if model is WorkItem:
                        await require(db, actor, item.access, retained=True)
    if current:
        state = await db.get(ConversationTaskState, row.conversation_id)
        if state and state.payload.get('latestMessageId') != row.message_id:
            problem(409, '已有后续请求，该问题已失效')
    return message


async def conversation_rows(db, actor, identifier):
    await owned(db, Conversation, identifier, actor)
    return list((await db.scalars(select(AssistantInteraction).where(AssistantInteraction.conversation_id == identifier, AssistantInteraction.owner_id == actor.id, AssistantInteraction.company_id == actor.company_id).order_by(AssistantInteraction.created_at.desc()).limit(30))).all())
