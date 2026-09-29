from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.db.idempotency import idem_begin, idem_save
from app.modules.interactions.models import AssistantInteraction
from app.modules.interactions.queries import validate
from app.modules.interactions.serializers import interaction_dto
from app.security.ownership import owned


def checked_answers(questions, answers):
    given = {answer.questionId: answer for answer in answers}
    if len(given) != len(answers) or set(given) != {q['id'] for q in questions}:
        problem(422, '请回答每个问题')
    result, parts = [], []
    for question in questions:
        answer = given[question['id']]
        options = {option['id']: option for option in question['options']}
        text = answer.text.strip()
        if len(set(answer.optionIds)) != len(answer.optionIds) or set(answer.optionIds) - options.keys():
            problem(422, '选项已变化，请重新选择')
        if question['type'] != 'multiple' and len(answer.optionIds) > 1:
            problem(422, '此问题只能选择一项')
        if question['type'] == 'text' and answer.optionIds or text and not question['allowCustom']:
            problem(422, '请按问题要求填写答案')
        if not answer.optionIds and not text:
            problem(422, '请先选择或填写答案')
        labels = [options[key]['label'] for key in answer.optionIds]
        result.append({'questionId': question['id'], 'optionIds': answer.optionIds, 'text': text})
        parts.append(question['prompt'] + '：' + '；'.join([*labels, *([text] if text else [])]))
    return result, '\n'.join(parts)


async def answer(db, actor, identifier, body, key):
    prior, request_digest = await idem_begin(db, actor, 'interaction-answer:' + identifier, key, body.model_dump())
    row = await owned(db, AssistantInteraction, identifier, actor, lock=True)
    if prior:
        await validate(db, actor, row)
        return prior
    answers, text = checked_answers(row.questions, body.answers)
    if row.state == 'answered':
        if row.answers != answers:
            problem(409, '此问题已经回答，不能重复修改')
        return {'interaction': await interaction_dto(db, actor, row), 'continuation': row.continuation or None}
    version(row, body.expectedRevision)
    if row.state != 'waiting':
        problem(409, '该问题已失效，不能再回答')
    source = await validate(db, actor, row, current=True)
    from app.tasks.interactions import continue_task
    continuation = await continue_task(db, actor, source, text, reference={'interactionId': row.id}, task_id=row.task_id)
    row.state, row.answers, row.continuation = 'answered', answers, continuation
    row.revision += 1
    row.updated_at = now()
    from app.tasks.waiting import settle
    await settle(db, actor, row.message_id)
    value = {'interaction': await interaction_dto(db, actor, row), 'continuation': continuation}
    return idem_save(db, actor, 'interaction-answer:' + identifier, key, request_digest, value)


async def cancel(db, actor, identifier, expected):
    row = await owned(db, AssistantInteraction, identifier, actor, lock=True)
    if row.state in ('cancelled', 'expired'):
        return {'interaction': await interaction_dto(db, actor, row)}
    version(row, expected)
    if row.state != 'waiting':
        problem(409, '此问题已经回答')
    source = await validate(db, actor, row, current=True)
    from app.tasks.models import Job
    from app.modules.conversations.task_state import cancel as cancel_task
    job = await db.get(Job, row.job_id)
    await cancel_task(db, actor, job, source)
    row.state, row.updated_at = 'cancelled', now()
    row.revision += 1
    job.state, job.phase = 'cancelled', 'cancelled'
    from app.tasks.outcomes import derive
    job.result = {**job.result, 'taskOutcome': derive(job)}
    from app.tasks.waiting import settle
    await settle(db, actor, row.message_id)
    return {'interaction': await interaction_dto(db, actor, row)}
