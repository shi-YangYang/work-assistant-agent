"""Validated user gaps persist once; failures never manufacture questions."""
import json

import pytest
from sqlalchemy import select

from app.agent.actions.clarification import ask_missing
from app.agent.actions.operations import execute
from app.modules.interactions.models import AssistantInteraction
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from _support.agent.business_actions import Judge, create, read_work
from _support.agent.execution_permissions import mode_runtime

pytestmark = pytest.mark.asyncio


def gap(field='content', candidates=()):
    return {'category': 'missing_info', 'recovery': {'owner': 'user', 'nextAction': 'ask',
        'missingInputs': [{'field': field, 'question': '请说明之前内容的范围。',
            'unavailableFromSources': '来源不能确定所指内容', 'candidateIds': list(candidates)}]}}


async def test_waiting_proposal_reuses_form_and_blocks_dependency_without_another_judge(setup):
    _, sessions, _, clients = setup
    context, sent = await mode_runtime(setup, 'full', '将之前的内容加入工作')
    context.intent_model = Judge(False, failure_kind='missing_info')
    args = {'step': 1, 'action': 'create_work', 'changes': {'title': '候选工作'}}
    first = await execute(context, **args)
    repeated = await execute(context, **args)
    dependent = await execute(context, step=2, action='create_work', changes={'title': '依赖工作'}, requires_step=1)
    assert first == repeated and first['state'] == 'waiting'
    assert dependent['state'] == 'waiting' and dependent['interactionId'] == first['interactionId']
    assert len(context.intent_model.inputs) == 1
    async with sessions() as db:
        panels = (await db.scalars(select(AssistantInteraction).where(AssistantInteraction.message_id == sent['messageId']))).all()
        assert len(panels) == 1 and panels[0].questions[0]['type'] == 'text'
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))
    # An old replay that encounters an already processed panel must not turn
    # its denied proposal into a success or execute using the previous guess.
    async with sessions.begin() as db:
        panel = await db.get(AssistantInteraction, first['interactionId'])
        panel.state = 'answered'
    replayed = await execute(context, **args)
    assert replayed['state'] == 'failed' and replayed['category'] == 'invalid_arguments'
    assert replayed['recovery']['nextAction'] == 'stop'
    async with sessions() as db:
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))


@pytest.mark.parametrize('kind', ['invalid_arguments', 'permission_denied', 'conflict', 'not_requested'])
async def test_authorization_failures_do_not_create_questions(setup, kind):
    _, sessions, _, _ = setup
    context, sent = await mode_runtime(setup, 'full')
    context.intent_model = Judge(False, failure_kind=kind)
    result = await execute(context, step=1, action='create_work', changes={'title': '候选'})
    assert result['state'] != 'waiting'
    async with sessions() as db:
        assert not await db.scalar(select(AssistantInteraction.id).where(AssistantInteraction.message_id == sent['messageId']))
        assert not await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == sent['messageId']))


async def test_internal_or_incomplete_contracts_never_become_questions():
    malformed = gap('bodyEdits')
    assert await ask_missing(None, malformed) is None
    malformed = gap()
    malformed['recovery']['missingInputs'][0].pop('unavailableFromSources')
    assert await ask_missing(None, malformed) is None
    for owner in ('assistant', 'system', 'none'):
        value = gap()
        value['recovery']['owner'] = owner
        assert await ask_missing(None, value) is None
    assert await ask_missing(None, {**gap(), 'category': 'transient_failure'}) is None


async def test_stale_foreign_and_unread_candidates_become_open_question_without_identifiers(setup):
    _, sessions, _, clients = setup
    context, sent = await mode_runtime(setup, 'full')
    stale = await create(clients['employee'], '旧工作')
    unread = await create(clients['employee'], '未读取工作')
    foreign = await create(clients['peer'], '不可公开工作')
    await read_work(context, stale['id'])
    context.read_versions[foreign['id']] = foreign['revision']
    async with sessions.begin() as db:
        item = await db.get(WorkItem, stale['id'])
        item.revision += 1
    ids = [stale['id'], unread['id'], foreign['id']]
    value = gap('target', ids)
    value['recovery']['missingInputs'][0]['question'] = '选择目标：' + '、'.join(ids)
    asked = await ask_missing(context, value)
    async with sessions() as db:
        panel = await db.get(AssistantInteraction, asked['interactionId'])
        question = panel.questions[0]
        assert question['type'] == 'text' and question['options'] == []
        assert not any(identifier in json.dumps(panel.questions) for identifier in ids)


async def test_generic_material_meaning_stays_open_and_valid_candidate_label_is_actual(setup):
    _, sessions, _, clients = setup
    context, _ = await mode_runtime(setup, 'full')
    work = await create(clients['employee'], '真实工作')
    await read_work(context, work['id'])
    value = gap('target', [work['id']])
    value['recovery']['missingInputs'].append(gap('materials')['recovery']['missingInputs'][0])
    asked = await ask_missing(context, value)
    async with sessions() as db:
        panel = await db.get(AssistantInteraction, asked['interactionId'])
        target, materials = panel.questions
        assert target['options'][0]['label'] == work['title']
        assert materials['prompt'] == '请说明之前内容的范围。'
        assert materials['type'] == 'text' and not materials['options']
