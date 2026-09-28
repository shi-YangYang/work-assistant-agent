from app.core.errors import problem
from app.core.versions import version
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.operations.writes import deletion_impact as writes_deletion_impact
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem
from app.security.access import require as business_require
from app.security.ownership import owned


async def read_target(db, actor, action, identifier):
    if action.endswith('work'):
        item = await owned(db, WorkItem, identifier, actor, lock=True)
        await business_require(db, actor, item.access, retained=True)
    else:
        item = await owned(db, Report, identifier, actor, read=action == 'delete_report', lock=True)
        if action == 'delete_report' and actor.role == 'admin':
            await writes_deletion_impact(db, item, actor)
        elif actor.role != 'employee':
            problem(403, '管理员不能代员工管理或提交个人报告')
    return item


async def source_check(db, actor, row):
    await business_require(db, actor, row.access, latest=True)
    message = await db.get(Message, row.message_id)
    if not message or message.deleted or message.owner_id != actor.id or message.company_id != actor.company_id:
        problem(409, '发起操作的消息已删除，请重新提出请求')
    conversation = await owned(db, Conversation, row.conversation_id, actor) if row.conversation_id else None
    if row.task_id and conversation:
        from app.modules.conversations.models import ConversationTaskState
        state = await db.get(ConversationTaskState, conversation.id)
        if state and state.payload.get('task', {}).get('id') == row.task_id and state.payload['task'].get('state') == 'cancelled':
            problem(409, '任务已中断，不能继续确认旧操作')
        if state and state.payload.get('task', {}).get('id') and state.payload['task']['id'] != row.task_id and state.payload.get('latestMessageId') != message.id:
            problem(409, '任务已被后续请求替换，本次操作不再有效')
    if message.transcript_revision != row.params.get('sourceRevision', message.transcript_revision):
        problem(409, '原始材料已更正，请重新提出请求')
    from app.modules.conversations.task_state import source_text
    for source in row.params.get('taskSources', []):
        if await source_text(db, actor, row.conversation_id, source) is None:
            problem(409, '任务授权来源已变化，请重新提出请求')
    for aid, revision in row.params.get('documents', {}).items():
        attachment = await owned(db, Attachment, aid, actor)
        if attachment.extraction_revision != revision:
            problem(409, '文件内容已变化，请重新提出请求')


async def preview(db, actor, row):
    if row.action == 'create_work':
        from app.modules.work.schemas import Progress
        changes = Progress(**row.params['changes']).model_dump(mode='json')
        return {'title': changes['title'], 'changes': changes, 'revision': 0}
    if row.action == 'generate_report':
        from datetime import date
        if row.params['kind'] not in ('daily', 'weekly'):
            problem(422, '报告类型无效')
        day = date.fromisoformat(row.params['date'])
        return {'title': f"{day} {'日报' if row.params['kind'] == 'daily' else '周报'}", 'changes': {'范围': '生成草稿，不包含提交'}, 'revision': 0}
    target = await read_target(db, actor, row.action, row.params['targetId'])
    version(target, row.params['expectedRevision'])
    if row.action in ('update_work', 'edit_report'):
        changes = row.params['changes']
        if row.action == 'update_work':
            from app.modules.work.schemas import Progress
            Progress(**{**target.content, **changes})
        return {'title': target.title if isinstance(target, WorkItem) else f'{target.period} {target.kind}', 'changes': changes, 'before': {key: target.content.get(key) for key in changes}, 'revision': target.revision}
    if row.action == 'submit_report':
        if not any(str(v).strip() for v in target.content.values()):
            problem(422, '请先填写报告内容')
        return {'title': f'{target.period} {"日报" if target.kind == "daily" else "周报"}', 'content': target.content, 'revision': target.revision}
    impact = await writes_deletion_impact(db, target, actor)
    return {'title': target.title if isinstance(target, WorkItem) else f'{target.period} {"日报" if target.kind == "daily" else "周报"}', 'impact': impact, 'revision': target.revision}
