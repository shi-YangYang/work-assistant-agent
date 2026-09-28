"""Bridge durable waiting items into one logical assistant task."""
from app.core.digests import digest
from app.core.errors import problem
from app.db.base import now
from app.modules.interactions.models import AssistantInteraction
from app.modules.interactions.schemas import Question
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.security.ownership import owned
from app.tasks.lease import lease
from sqlalchemy import select


async def ask(context, raw_questions, *, continue_task=False):
    questions = [Question.model_validate(value) for value in raw_questions]
    if not 1 <= len(questions) <= 3 or len({q.id for q in questions}) != len(questions):
        problem(422, '一次请集中提出 1～3 个不同问题')
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        source = await owned(db, Message, job.target_id, actor)
        from app.agent.task_context import load
        snapshot = await load(context, db, actor, job, source)
        if continue_task and snapshot.get('previousTask'):
            from app.modules.conversations.task_state import resume
            snapshot = await resume(db, actor, job, source, requested=True)
            context.task_snapshot = snapshot
            await settle_natural_reply(db, actor, job, {'relation': 'continue'})
        values = [q.model_dump() for q in questions]
        for question in values:
            for option in question['options']:
                if bool(option['objectType']) != bool(option['objectId']):
                    problem(422, '对象选项需要真实的类型和 ID')
                if not option['objectId']:
                    continue
                identifier, kind = option['objectId'], option['objectType']
                from app.modules.work.models import WorkItem
                from app.modules.reports.models import Report
                if kind == 'member':
                    evidence = next((v for v in job.access.get('reads', {}).values() if v.get('type') == kind and v.get('id') == identifier), None)
                    if not evidence:
                        problem(422, '请先查询真实候选对象')
                    from app.security.access import employee
                    item = await employee(db, actor, identifier)
                    option['label'], option['description'] = item.name, ''
                else:
                    item = await owned(db, WorkItem if kind == 'work' else Report, identifier, actor, read=True)
                    if context.read_versions.get(identifier) != item.revision:
                        problem(422, '请先读取候选对象的最新版本')
                    if item.owner_id != actor.id:
                        from app.security.access import resolve
                        evidence = next((v for v in job.access.get('reads', {}).values() if v.get('type') == kind and v.get('id') == identifier), None)
                        if not evidence:
                            problem(403, '无权使用该候选对象')
                        await resolve(db, actor, evidence, latest=True)
                    option['objectRevision'] = item.revision
                    option['label'] = item.title if kind == 'work' else f'{item.period} {"日报" if item.kind == "daily" else "周报"}'
                    option['description'] = item.content.get('summary', '')[:160] if kind == 'work' and item.owner_id == actor.id else ''
        # A model may reuse short IDs such as `details` across task stages.
        # Deduplicate the actual missing information, not those arbitrary IDs.
        key = digest([{**q, 'prompt': q['prompt'].strip(), 'options': [{k: v for k, v in option.items() if k != 'objectRevision'} for option in q['options']]} for q in values])
        prior = await db.scalar(select(AssistantInteraction).where(AssistantInteraction.task_id == snapshot['taskId'], AssistantInteraction.key == key))
        if prior:
            return {'state': 'waiting' if prior.state == 'waiting' else prior.state, 'interactionId': prior.id, 'message': '等待用户回答' if prior.state == 'waiting' else '这个问题已经处理，使用已有答案，不要再次提问'}
        from app.modules.interactions.service import expire
        await expire(db, conversation_id=source.conversation_id)
        row = AssistantInteraction(company_id=actor.company_id, owner_id=actor.id, conversation_id=source.conversation_id,
            message_id=source.id, job_id=job.id, task_id=snapshot['taskId'], key=key, source_revision=source.transcript_revision,
            questions=values, sources=[*snapshot.get('directives', []), *snapshot.get('previousTask', {}).get('sources', [])], access=job.access)
        db.add(row)
        await db.flush()
        job.result = {**job.result, 'waitingInteractionId': row.id}
        return {'state': 'waiting', 'interactionId': row.id, 'message': '问题已展示，请等待用户回答；不要执行依赖答案的操作'}


async def pending(db, actor, job, message):
    question = await db.scalar(select(AssistantInteraction).where(AssistantInteraction.message_id == message.id, AssistantInteraction.state == 'waiting'))
    action = await db.scalar(select(BusinessAction).where(BusinessAction.message_id == message.id, BusinessAction.state == 'pending'))
    return question, action


async def waiting_text(context, *, include_actions=True):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        question, action = await pending(db, actor, job, message)
        return '请补充下面的信息，我会继续原任务。' if question else '请确认下方操作，确认后继续原任务。' if action and include_actions else None


async def finish_waiting(context, answer=None):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        question, action = await pending(db, actor, job, message)
        if not question and not action:
            return False
        if not question and answer is not None and answer != '请确认下方操作，确认后继续原任务。':
            return False
        from app.modules.operations.receipts import message_actions, receipt_summary
        cards = await message_actions(db, actor, message)
        message.reply = '请补充下面的信息，我会继续原任务。' if question else receipt_summary(cards)
        message.access = job.access
        job.state, job.phase, job.error = 'awaiting_input', 'awaiting_answer' if question else 'awaiting_confirmation', ''
        job.lease_until, job.updated_at = None, now()
        interpretation = {**job.result.get('intentTaskInterpretation', {}), 'state': 'needs_input' if question else 'needs_confirmation', 'remaining': [q['prompt'] for q in question.questions] if question else [], 'relation': job.result.get('taskSnapshot', {}).get('relation', 'new')}
        from app.tasks.outcomes import derive
        job.result = {**job.result, 'taskInterpretation': interpretation}
        outcome = derive(job, cards, interpretation=interpretation)
        job.result = {**job.result, 'taskOutcome': outcome}
        from app.modules.conversations.task_state import finish
        await finish(db, actor, job, message, interpretation, outcome)
        from app.tasks.feedback_state import update_feedback
        update_feedback(job, job.phase, '')
        return True


async def settle_natural_reply(db, actor, job, interpretation):
    candidate = job.result.get('questionCandidate')
    if not candidate:
        return
    row = await db.get(AssistantInteraction, candidate)
    if not row or row.state != 'waiting':
        return
    message = await owned(db, Message, job.target_id, actor)
    if interpretation.get('relation') == 'continue':
        row.state, row.answers = 'answered', [{'questionId': question['id'], 'optionIds': [], 'text': message.text} for question in row.questions]
        row.continuation = {'messageId': message.id, 'jobId': job.id, 'conversationId': message.conversation_id}
    else:
        row.state = 'expired'
    row.revision += 1
    row.updated_at = now()
    from app.tasks.waiting import settle
    await settle(db, actor, row.message_id)
