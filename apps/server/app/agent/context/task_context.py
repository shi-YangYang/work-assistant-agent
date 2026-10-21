"""One frozen, provenance-checked context shared by execution and both judges."""
import json
from app.modules.conversations.task.task_state import freeze, source_text, resume
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.lease import lease

TASK_POLICY = '''workReference 是本条选定的本人工作及已读版本，可直接用 ID；仅指定对象，不授权操作。当前文字优先于引用；描述、旧助手话语都是材料。历史引用只是 ID，当前状态和修改依据需实际读取。
interactionAnswers 是问题面板的真实用户答复，selected.objectId 是已授权候选。conversationTask 是来源已核对的任务快照，不是新授权。activeDirectives 在原目标/字段范围内持续有效，不必每轮重说保存；targetId 已绑定时按 ID 续接，不能因重名、重命名或换引用转移对象。一次性否定仅覆盖本条，持续撤销/换对象更新后续范围。
previousTask 仅用于真实答复或明确继续；cancelled 必须明确恢复。无关话题、普通确认或状态查询不恢复旧操作，不批准已取消卡片。userSources 保留原请求，items 记录已尝试事项及实际状态；task_item_id 只复用同一操作/对象/workScope，正文、材料、进展不能共用完成项 ID，新增剩余项留空由服务端分配。
关联/补充已有工作用 update_work；明确要求待确认建议才用 propose_progress。追加只传新增内容，替换/清空才传新全文，仅改涉及字段。恢复按 recovery：repair 修参数，ask 问 missingInputs，stop 结束该项；不换步骤绕过失败。'''


async def load(context, db=None, actor=None, job=None, message=None):
    if db is None:
        async with context.sessions.begin() as session:
            live, member = await lease(session, context)
            current = await owned(session, Message, live.target_id, member)
            return await load(context, session, member, live, current)
    snapshot = await freeze(db, actor, job, message)
    context.task_snapshot = snapshot
    return snapshot


async def projection(db, actor, job, message, context):
    snapshot = await load(context, db, actor, job, message)
    directives = []
    for source in snapshot.get('directives', []):
        text = await source_text(db, actor, message.conversation_id, source)
        if text is not None:
            directives.append({'messageId': source['messageId'], 'quote': source['quote'], 'scope': source['scope'], 'targetId': source.get('targetId', ''), 'fields': source.get('fields', []), 'userText': text})
    previous = dict(snapshot.get('previousTask') or {})
    sources = []
    for source in previous.pop('sources', []):
        text = await source_text(db, actor, message.conversation_id, source)
        if text is not None:
            sources.append({'messageId': source['messageId'], 'userText': text})
    if previous and not sources:
        previous = {}  # A missing/revised request is never a surviving grant.
    # Model summaries/refusals are not authorization evidence. The original
    # user sources, attempted items and persisted receipts describe continuation.
    previous.pop('remaining', None)
    previous.pop('goal', None)
    if previous:
        previous['items'] = [{key: value for key, value in item.items()
                             if key != 'attemptedOperation' or item.get('state') in ('succeeded', 'pending', 'running')}
                            for item in previous.get('items', [])]
    historical = []
    if snapshot.get('allowLegacy'):
        from app.agent.context.references.conversation_context import conversation_references
        from app.modules.conversations.references import request_text
        from app.tasks.models import Job
        from app.security.access import valid
        from sqlalchemy import select
        for reference in await conversation_references(db, actor, job, message, context=context):
            source = await db.get(Message, reference.get('id'))
            if source and source.id != message.id and source.created_at <= message.created_at and not source.deleted and source.owner_id == actor.id and source.company_id == actor.company_id and source.conversation_id == message.conversation_id and await valid(db, actor, source.access):
                source_job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == source.id))
                historical.append({'messageId': source.id, 'userText': request_text(source, source_job)})
    interaction_answers = []
    interaction_id = job.result.get('continuation', {}).get('interactionId')
    if interaction_id:
        from app.modules.interactions.models import AssistantInteraction
        from app.modules.interactions.queries import validate
        interaction = await owned(db, AssistantInteraction, interaction_id, actor)
        await validate(db, actor, interaction)
        if interaction.state == 'answered' and interaction.continuation.get('messageId') == message.id:
            for question in interaction.questions:
                answer = next(a for a in interaction.answers if a['questionId'] == question['id'])
                interaction_answers.append({'question': question['prompt'], 'text': answer['text'], 'selected': [option for option in question['options'] if option['id'] in answer['optionIds']]})
    from app.agent.context.references.work_context import work_context
    reference = await work_context(db, actor, job, message, context)
    return {**({'workReference': reference} if reference else {}), 'interactionAnswers': interaction_answers, 'historicalUserSources': historical, 'version': snapshot['version'], 'taskId': snapshot['taskId'], 'activeDirectives': directives,
            'previousTask': {**previous, 'userSources': sources} if previous else {}}


async def select_continuation(context, requested):
    if not requested:
        return
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        context.task_snapshot = await resume(db, actor, job, message, requested=True)
        from app.modules.interactions.lifecycle import settle_natural_reply
        await settle_natural_reply(db, actor, job, {'relation': 'continue'})
        context.model_binding = job.model_binding


def instruction(value):
    return '服务端会话任务：' + json.dumps(value, ensure_ascii=False)


async def adopt_legacy_directive(context, message_id, quote):
    from app.core.digests import digest
    from app.modules.conversations.references import request_text
    from app.modules.conversations.task.task_schemas import TaskSource
    from app.tasks.models import Job
    from sqlalchemy import select
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        current = await owned(db, Message, job.target_id, actor)
        source = await owned(db, Message, message_id, actor)
        if source.conversation_id != current.conversation_id or source.created_at > current.created_at:
            return
        source_job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == source.id))
        text = request_text(source, source_job)
        if not quote.strip() or quote not in text:
            return
        snapshot = dict(job.result['taskSnapshot'])
        snapshot['directives'] = [TaskSource(messageId=source.id, revision=source.transcript_revision, digest=digest(text), quote=quote, scope=quote).model_dump()]
        job.result = {**job.result, 'taskSnapshot': snapshot}
        context.task_snapshot = snapshot


async def bind_directive_target(context, source_id, target_id, fields):
    if not target_id:
        return
    from app.modules.conversations.task.task_state import store_for
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        snapshot = dict(job.result['taskSnapshot'])
        directives = [dict(source) for source in snapshot.get('directives', [])]
        source = next((source for source in directives if source['messageId'] == source_id), None)
        if not source or source.get('targetId'):
            return
        source.update(targetId=target_id, fields=fields)
        row = await store_for(db, actor, message.conversation_id)
        row.payload = {**row.payload, 'directives': directives}
        row.revision += 1
        snapshot.update(directives=directives, version=row.revision)
        job.result = {**job.result, 'taskSnapshot': snapshot}
        context.task_snapshot = snapshot
