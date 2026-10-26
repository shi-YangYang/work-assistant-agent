from app.core.errors import problem
from app.core.versions import version
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.operations.mutations.writes import deletion_impact as writes_deletion_impact
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem
from app.security.access import require as business_require, resolve as business_resolve
from app.modules.team.sources import canonical_token
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
    # Access retains every source seen in the conversation. Historical reads
    # must remain authorized, but only this operation's dependencies must be
    # current; an unrelated old query cannot block a new personal work edit.
    await business_require(db, actor, row.access)
    selected = set()
    for raw in row.params.get('sourceTokens', []):
        evidence = row.access.get('reads', {}).get(canonical_token(raw))
        if not evidence or evidence.get('type') not in ('work', 'report'):
            problem(403, '督办来源必须来自实际读取的工作或报告')
        await business_resolve(db, actor, evidence, latest=True)
        selected.add((evidence['type'], evidence['id'], evidence['ownerId']))
    if row.action == 'edit_report':
        from app.security.locks import company_lock
        await company_lock(db, actor.company_id)
        from app.modules.reports.generation.sources import report_fact_basis
        from app.core.digests import digest
        target = await read_target(db, actor, row.action, row.params['targetId'])
        facts = await report_fact_basis(db, actor, target, full=True)
        if not facts['complete'] or row.params.get('reportSourceDigest') != digest(facts):
            problem(409, '报告来源已变化，请重新读取后修改；原报告已保留')
    if row.action == 'update_work':
        target = await read_target(db, actor, row.action, row.params['targetId'])
        # Persisted links are also dependencies: omitting sourceTokens must not
        # bypass freshness. Links retain old revisions, so check the newest
        # saved revision unless this action explicitly selects its replacement.
        linked = {}
        for link in target.business_links:
            evidence = link['evidence']
            key = (evidence['type'], evidence['id'], evidence['ownerId'])
            if key not in linked or evidence.get('version', 0) > linked[key].get('version', 0):
                linked[key] = evidence
        for key, evidence in linked.items():
            if key not in selected:
                await business_resolve(db, actor, evidence, latest=True)
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
    from app.modules.conversations.task.task_state import source_text
    for source in row.params.get('taskSources', []):
        if await source_text(db, actor, row.conversation_id, source) is None:
            problem(409, '任务授权来源已变化，请重新提出请求')
    for aid, revision in row.params.get('documents', {}).items():
        from app.modules.attachments.documents import visible_attachment
        attachment = await visible_attachment(db, aid, actor)
        if attachment.extraction_revision != revision:
            problem(409, '文件内容已变化，请重新提出请求')


async def preview(db, actor, row):
    if row.action == 'create_work':
        from app.modules.work.schemas import Progress
        from app.modules.work.records.record_schemas import AgentWorkChanges
        changes = AgentWorkChanges.model_validate(row.params['changes']).model_dump(mode='json', exclude_unset=True)
        Progress(**{key: value for key, value in changes.items() if key in Progress.model_fields})
        from app.modules.work.agent.agent_commands import action_preview
        changes, names = await action_preview(db, actor, None, changes)
        return {'title': changes['title'], 'changes': changes, 'materialNames': names, 'revision': 0}
    if row.action == 'generate_report':
        from datetime import date
        if row.params['kind'] not in ('weekly',):
            problem(422, '报告类型无效')
        day = date.fromisoformat(row.params['date'])
        return {'title': f"{day} 周报", 'changes': {'范围': '生成草稿，不包含提交'}, 'revision': 0}
    target = await read_target(db, actor, row.action, row.params['targetId'])
    version(target, row.params['expectedRevision'])
    if row.action in ('update_work', 'edit_report'):
        changes = row.params['changes']
        if row.action == 'update_work':
            from app.modules.work.schemas import Progress
            Progress(**{key: value for key, value in {**target.content, **changes}.items() if key in Progress.model_fields})
            from app.modules.work.agent.agent_commands import action_preview
            changes, names = await action_preview(db, actor, target, changes)
        return {'title': target.title if isinstance(target, WorkItem) else f'{target.period} {target.kind}', 'changes': changes, 'before': {key: target.content.get(key) for key in changes}, 'materialNames': names if row.action == 'update_work' else {}, 'revision': target.revision}
    if row.action == 'submit_report':
        if not any(str(v).strip() for v in target.content.values()):
            problem(422, '请先填写报告内容')
        return {'title': f'{target.period} 周报', 'content': target.content, 'revision': target.revision}
    impact = await writes_deletion_impact(db, target, actor)
    return {'title': target.title if isinstance(target, WorkItem) else f'{target.period} 周报', 'impact': impact, 'revision': target.revision}
