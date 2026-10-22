"""Persist validated authorization gaps before any business write."""
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.actions.interactions import ask
from app.core.digests import digest
from app.modules.interactions.schemas import MAX_QUESTIONS, MAX_QUESTION_OPTIONS
from app.modules.work.models import WorkItem
from app.security.access import valid
from app.tasks.lease import lease


async def ask_missing(context, result):
    recovery = result.get('recovery') or {}
    if (result.get('category') not in ('missing_info', 'not_requested') or recovery.get('owner') != 'user'
            or recovery.get('nextAction') != 'ask'):
        return None
    # authorize_intent has already checked evidence and recovery ownership.
    # Older cached barriers still have to carry the complete typed contract;
    # neither field errors nor refusal prose can create a user question.
    from app.agent.actions.intent import MissingInput
    try:
        missing = [MissingInput.model_validate(value) for value in recovery.get('missingInputs', [])]
    except (ValidationError, TypeError):
        return None
    if not 1 <= len(missing) <= MAX_QUESTIONS or len({item.field for item in missing}) != len(missing):
        return None
    if recovery.get('materialSelectionId') and {item.field for item in missing} == {'target'}:
        from app.agent.actions.material_questions import ask_destination
        return await ask_destination(context, recovery=recovery)

    async with context.sessions.begin() as db:
        _, actor = await lease(db, context)
        candidate_ids = {identifier for item in missing if item.field == 'target' for identifier in item.candidateIds}
        works = (await db.scalars(select(WorkItem).where(
            WorkItem.id.in_(candidate_ids & context.read_versions.keys()),
            WorkItem.company_id == actor.company_id, WorkItem.owner_id == actor.id,
            WorkItem.deleted.is_(False)))).all()
        candidates = {work.id: {'id': 'work-' + work.id, 'label': work.title[:120],
            'objectType': 'work', 'objectId': work.id} for work in works
            if context.read_versions[work.id] == work.revision
            and await valid(db, actor, work.access, retained=True)}
        questions = []
        for item in missing:
            options = [candidates[identifier] for identifier in dict.fromkeys(item.candidateIds)
                       if identifier in candidates] if item.field == 'target' else []
            # Never repeat an unavailable candidate's name or ID from the
            # judge's old question. An open answer does not choose a fallback.
            safe_target = item.field == 'target' and set(item.candidateIds) - candidates.keys()
            questions.append({'id': 'clarify-' + item.field + '-' + digest({
                'item': result.get('taskItemId', ''), 'field': item.field})[:24],
                'prompt': '请说明要操作的目标。' if safe_target else item.question,
                'type': 'single' if options else 'text', 'options': options[:MAX_QUESTION_OPTIONS], 'allowCustom': True})
    return await ask(context, questions, append_pending=True)


async def rejected_operation(context, proposal, reason):
    """Preserve denial while routing a validated user gap without another model."""
    category = context.authorization_outcomes.get(digest(proposal), 'invalid_arguments')
    from app.tasks.feedback.public import message as public_message
    result = {'state': 'clarification' if category == 'missing_info' else 'failed', 'category': category,
            'taskItemId': context.task_item_keys.get(digest(proposal), ''),
            'fieldIssues': context.authorization_details.get(digest(proposal), []),
            'recovery': context.authorization_recovery.get(digest(proposal), {
                'owner': 'none' if category == 'not_requested' else 'system' if category == 'permission_denied' else 'assistant',
                'missingInputs': [], 'nextAction': 'stop' if category in ('not_requested', 'permission_denied') else 'repair',
                'code': 'operation_mismatch'}),
            'diagnostic': reason, 'message': reason}
    question = await ask_missing(context, result)
    if question:
        if question['state'] == 'waiting':
            return {**result, **question, 'message': '等待用户回答',
                    'publicMessage': '请补充下面的信息，我会继续原任务。'}
        # An answered/expired panel is not authorization for this old
        # proposal. Only the ordinary answer-created message may resume it.
        return {**result, 'state': 'failed', 'category': 'invalid_arguments',
                'recovery': {'owner': 'assistant', 'missingInputs': [], 'nextAction': 'stop',
                             'code': 'interaction_already_processed'},
                'publicMessage': '这项操作尚未执行，请查看后续答复。'}
    if category == 'not_requested':
        result['state'] = 'not_requested'
    return {**result, 'publicMessage': public_message(result)}
