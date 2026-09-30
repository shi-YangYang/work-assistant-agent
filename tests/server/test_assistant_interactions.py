import pytest
from sqlalchemy import select, func
from app.agent.actions.interactions import ask, finish_waiting
from app.modules.interactions.lifecycle import settle_natural_reply
from app.agent.context.task_context import load
from app.modules.interactions.models import AssistantInteraction
from app.modules.messages.models import Message
from app.tasks.models import Job
from app.tasks.lease import lease
from test_execution_permissions import mode_runtime
from test_business_actions import create, read_work
from test_company import keyed

pytestmark = pytest.mark.asyncio


def questions():
    return [
        {'id': 'target', 'prompt': '选择方向', 'type': 'single', 'options': [{'id': 'a', 'label': '开发'}, {'id': 'b', 'label': '测试'}]},
        {'id': 'scope', 'prompt': '选择范围', 'type': 'multiple', 'options': [{'id': 'web', 'label': 'Web'}, {'id': 'desktop', 'label': '桌面'}]},
        {'id': 'date', 'prompt': '截止日期', 'type': 'text'},
    ]


async def test_durable_questions_structured_answers_and_duplicate_continuation(setup):
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'auto', '帮我安排一项工作，但先确认方向范围日期')
    first = await ask(context, questions())
    second = await ask(context, questions())
    assert first['interactionId'] == second['interactionId']
    assert await finish_waiting(context)
    page = (await clients['employee'].get(f"/api/v1/conversations/{sent['conversationId']}/interactions")).json()
    interaction = page['items'][0]
    assert interaction['state'] == 'waiting'
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['job']['state'] == 'awaiting_input'
    assert message['job']['taskOutcome']['state'] == 'needs_input'
    assert message['interactions'] == page['items']
    body = {'expectedRevision': interaction['revision'], 'answers': [{'questionId': 'target', 'optionIds': ['a']}, {'questionId': 'scope', 'optionIds': ['web', 'desktop']}, {'questionId': 'date', 'text': '2026-10-01'}]}
    headers = keyed()
    response = await clients['employee'].post('/api/v1/interactions/' + interaction['id'] + '/answer', json=body, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['interaction']['state'] == 'answered'
    repeated = await clients['employee'].post('/api/v1/interactions/' + interaction['id'] + '/answer', json=body, headers=keyed())
    assert repeated.json() == data
    same_key = await clients['employee'].post('/api/v1/interactions/' + interaction['id'] + '/answer', json=body, headers=headers)
    assert same_key.json() == data
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == users['employee'].id)) == 2
        answer = await db.get(Message, data['continuation']['messageId'])
        assert '开发' in answer.text and 'Web；桌面' in answer.text


async def test_question_owner_version_cancellation_and_source_changes(setup):
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'full', '工作截止哪天需要确认')
    asked = await ask(context, [{'id': 'date', 'prompt': '截止日期是哪天', 'type': 'text'}])
    assert await finish_waiting(context)
    endpoint = '/api/v1/interactions/' + asked['interactionId']
    body = {'expectedRevision': 1, 'answers': [{'questionId': 'date', 'text': '下周五'}]}
    assert (await clients['peer'].post(endpoint + '/answer', json=body, headers=keyed())).status_code == 404
    assert (await clients['employee'].post(endpoint + '/answer', json={**body, 'expectedRevision': 9}, headers=keyed())).status_code == 409
    cancelled = await clients['employee'].post(endpoint + '/cancel', json={'expectedRevision': 1})
    assert cancelled.json()['interaction']['state'] == 'cancelled'
    assert (await clients['employee'].post(endpoint + '/answer', json=body, headers=keyed())).status_code == 409


async def test_object_options_use_real_read_labels_and_recheck_deletion(setup):
    _, sessions, _, clients = setup
    work = await create(clients['employee'], '真实标题')
    context, sent = await mode_runtime(setup, 'auto', '你说的是哪一项')
    q = [{'id': 'target', 'prompt': '选择工作', 'type': 'single', 'options': [{'id': 'a', 'label': '伪造标题', 'objectType': 'work', 'objectId': work['id']}]}]
    with pytest.raises(Exception):
        await ask(context, q)
    await read_work(context, work['id'])
    result = await ask(context, q)
    await finish_waiting(context)
    value = (await clients['employee'].get(f"/api/v1/conversations/{sent['conversationId']}/interactions")).json()['items'][0]
    assert value['questions'][0]['options'][0]['label'] == '真实标题'
    async with sessions.begin() as db:
        from app.modules.work.models import WorkItem
        item = await db.get(WorkItem, work['id'])
        item.deleted = True
    response = await clients['employee'].post('/api/v1/interactions/' + result['interactionId'] + '/answer', json={'expectedRevision': 1, 'answers': [{'questionId': 'target', 'optionIds': ['a']}]}, headers=keyed())
    assert response.status_code in (404, 409)
    value = (await clients['employee'].get(f"/api/v1/conversations/{sent['conversationId']}/interactions")).json()['items'][0]
    assert value['state'] == 'expired' and value['questions'] == []


async def test_structured_answer_binds_same_name_object_id_and_task(setup):
    from app.tasks.runtime.queue import claim
    from app.tasks.context import RunContext
    from app.agent.context.task_context import projection
    _, sessions, users, clients = setup
    first = await create(clients['employee'], '同名', summary='第一个')
    second = await create(clients['employee'], '同名', summary='第二个')
    context, sent = await mode_runtime(setup, 'auto', '完成同名的那项')
    await read_work(context, first['id']); await read_work(context, second['id'])
    asked = await ask(context, [{'id': 'work', 'prompt': '完成哪项？', 'type': 'single', 'options': [{'id': 'a', 'label': '任意', 'objectType': 'work', 'objectId': first['id']}, {'id': 'b', 'label': '任意', 'objectType': 'work', 'objectId': second['id']}]}])
    await finish_waiting(context)
    answer = await clients['employee'].post('/api/v1/interactions/' + asked['interactionId'] + '/answer', json={'expectedRevision': 1, 'answers': [{'questionId': 'work', 'optionIds': ['b']}]}, headers=keyed())
    assert answer.status_code == 200, answer.text
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, context.settings, source_revision=0)
    async with sessions.begin() as db:
        live, actor = await lease(db, context)
        message = await db.get(Message, live.target_id)
        value = await projection(db, actor, live, message, context)
        assert value['taskId'] == sent['messageId']
        assert value['interactionAnswers'][0]['selected'][0]['objectId'] == second['id']


@pytest.mark.parametrize('relation,state', [('continue', 'answered'), ('new', 'expired')])
async def test_normal_message_consumes_answer_only_after_semantic_continuation(setup, relation, state):
    from app.tasks.runtime.queue import claim
    from app.modules.conversations.task.task_state import finish
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'auto', '安排截止日期')
    result = await ask(context, [{'id': 'date', 'prompt': '哪一天', 'type': 'text'}])
    await finish_waiting(context)
    reply = await clients['employee'].post('/api/v1/messages', json={'conversationId': sent['conversationId'], 'text': '下周五' if relation == 'continue' else '先不做了，解释什么是API'}, headers=keyed())
    assert reply.status_code == 202
    async with sessions.begin() as db:
        job = await db.get(Job, reply.json()['jobId'])
        assert job.result['questionCandidate'] == result['interactionId']
        await settle_natural_reply(db, users['employee'], job, {'relation': relation})
        row = await db.get(AssistantInteraction, result['interactionId'])
        assert row.state == state
        assert bool(row.continuation) == (relation == 'continue')


async def test_harness_questions_stop_before_parallel_write_or_second_model_call(setup):
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.tasks.processing.handlers import process_job
    from app.modules.work.models import WorkItem
    from pydantic import Field
    class AskingModel(ChatOpenAI):
        calls: int = 0
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            assert self.calls == 1, 'Waiting must not consume more model calls'
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{'id': 'question', 'name': 'request_user_input', 'args': {'questions': [{'id': 'target', 'prompt': '选择目标', 'type': 'text'}]}}, {'id': 'write', 'name': 'execute_business_action', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '不应写入'}}}]))])
    settings, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'full', '缺少目标，先问我再创建')
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=AskingModel(model='test', api_key='test'))
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['job']['state'] == 'awaiting_input', message
    assert message['job']['phase'] == 'awaiting_answer'
    assert message['interactions'][0]['state'] == 'waiting'
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.lease_until is None
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id)) == 0


async def test_answered_choice_keeps_own_task_changes_but_rejects_external_edits(setup):
    from app.agent.actions.operations import execute
    from app.tasks.runtime.queue import claim
    from app.tasks.context import RunContext
    from test_business_actions import Judge
    settings, sessions, users, clients = setup
    work = await create(clients['employee'], '选择后更新', summary='原内容')
    context, sent = await mode_runtime(setup, 'ask', '选择工作后将状态改为已完成')
    await read_work(context, work['id'])
    asked = await ask(context, [{'id': 'work', 'prompt': '选择工作', 'type': 'single', 'options': [{'id': 'a', 'label': '选择后更新', 'objectType': 'work', 'objectId': work['id']}]}])
    await finish_waiting(context)
    answered = await clients['employee'].post('/api/v1/interactions/' + asked['interactionId'] + '/answer', json={'expectedRevision': 1, 'answers': [{'questionId': 'work', 'optionIds': ['a']}]}, headers=keyed())
    assert answered.status_code == 200, answered.text
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, intent_model=Judge())
    await read_work(context, work['id'])
    action = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'status': 'done'})
    await finish_waiting(context)
    approved = await clients['employee'].post('/api/v1/business-actions/' + action['id'] + '/confirm', json={'expectedRevision': action['revision']})
    assert approved.status_code == 200, approved.text
    endpoint = f"/api/v1/conversations/{sent['conversationId']}/interactions"
    row = (await clients['employee'].get(endpoint)).json()['items'][0]
    assert row['state'] == 'answered' and row['answers'] == answered.json()['interaction']['answers']
    assert row['continuation'] == answered.json()['continuation']
    changed = await clients['employee'].post('/api/v1/work-items/' + work['id'] + '/progress', json={'title': work['title'], 'summary': '外部修改', 'expectedRevision': 2})
    assert changed.status_code == 200, changed.text
    row = (await clients['employee'].get(endpoint)).json()['items'][0]
    assert row['state'] == 'expired' and row['questions'] == []


async def test_same_question_id_can_request_different_missing_information(setup):
    from app.tasks.runtime.queue import claim
    from app.tasks.context import RunContext
    settings, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'auto', '先确认项目名称，再确认交付要求')
    first = await ask(context, [{'id': 'details', 'prompt': '项目名称是什么？', 'type': 'text'}])
    await finish_waiting(context)
    response = await clients['employee'].post('/api/v1/interactions/' + first['interactionId'] + '/answer', json={'expectedRevision': 1, 'answers': [{'questionId': 'details', 'text': '客户端升级'}]}, headers=keyed())
    assert response.status_code == 200, response.text
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    second = await ask(context, [{'id': 'details', 'prompt': '交付要求是什么？', 'type': 'text'}])
    assert second['state'] == 'waiting' and second['interactionId'] != first['interactionId']
    duplicate = await ask(context, [{'id': 'details', 'prompt': '交付要求是什么？', 'type': 'text'}])
    assert duplicate['interactionId'] == second['interactionId'] and duplicate['state'] == 'waiting'


@pytest.mark.parametrize('next_stage', ['approval', 'question'])
async def test_natural_answer_is_consumed_before_next_waiting_stage(setup, next_stage):
    import json
    from langchain_core.messages import AIMessage
    from app.agent.actions.operations import execute
    from app.tasks.context import RunContext
    from app.tasks.runtime.queue import claim
    from test_business_actions import Judge
    settings, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'ask', '问我项目名称，再创建工作')
    first = await ask(context, [{'id': 'name', 'prompt': '项目名称是什么？', 'type': 'text'}])
    await finish_waiting(context)
    response = await clients['employee'].post('/api/v1/messages', json={'conversationId': sent['conversationId'], 'text': '客户端升级'}, headers=keyed())
    assert response.status_code == 202, response.text
    job = await claim(sessions, users['employee'].id)
    class ResumeJudge(Judge):
        async def ainvoke(self, messages):
            result = await super().ainvoke(messages)
            return AIMessage(content=json.dumps({**json.loads(result.content), 'resumeTask': True}))
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, intent_model=ResumeJudge())
    if next_stage == 'approval':
        result = await execute(context, step=1, action='create_work', changes={'title': '客户端升级'})
        assert result['state'] == 'pending'
    else:
        result = await ask(context, [{'id': 'date', 'prompt': '截止日期？', 'type': 'text'}], continue_task=True)
        assert result['state'] == 'waiting'
    assert await finish_waiting(context)
    rows = (await clients['employee'].get(f"/api/v1/conversations/{sent['conversationId']}/interactions")).json()['items']
    first_row = next(row for row in rows if row['id'] == first['interactionId'])
    assert first_row['state'] == 'answered' and first_row['answers'][0]['text'] == '客户端升级', first_row


@pytest.mark.parametrize('decision', ['answer', 'cancel'])
async def test_resolved_question_converges_source_job_http_and_sse(setup, decision):
    import json
    _, sessions, _, clients = setup
    context, sent = await mode_runtime(setup, 'auto', '先确定截止日期')
    question = await ask(context, [{'id': 'date', 'prompt': '哪天完成？', 'type': 'text'}])
    await finish_waiting(context)
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'nodeExecution': {'scope': 's', 'nodes': [{'id': 'q', 'scope': 's', 'kind': 'tool', 'label': '等待用户回答', 'state': 'awaiting_input', 'attempts': 1, 'output': {'content': json.dumps(question)}}]}}
    endpoint = '/api/v1/interactions/' + question['interactionId'] + '/' + decision
    body = {'expectedRevision': 1, **({'answers': [{'questionId': 'date', 'text': '下周五'}]} if decision == 'answer' else {})}
    result = await clients['employee'].post(endpoint, json=body, headers=keyed())
    assert result.status_code == 200, result.text
    expected = 'succeeded' if decision == 'answer' else 'cancelled'
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    job = message['job']
    assert job['state'] == expected and job['phase'] == ('complete' if decision == 'answer' else 'cancelled'), job
    assert job['nodes'][0]['state'] == expected
    assert job['taskOutcome']['nextAction'] == 'none'
    feedback = (await clients['employee'].get('/api/v1/jobs/' + sent['jobId'] + '/feedback')).json()
    assert feedback['nodes'] == job['nodes'] and feedback['taskOutcome'] == job['taskOutcome']
    stream = await clients['employee'].get('/api/v1/jobs/' + sent['jobId'] + '/events')
    assert stream.status_code == 200 and 'awaiting_input' not in stream.text


async def test_expired_question_closes_waiting_node_without_reviving_sources(setup):
    import json
    from app.modules.interactions.lifecycle import expire
    _, sessions, users, clients = setup
    context, sent = await mode_runtime(setup, 'auto', '确认材料')
    question = await ask(context, [{'id': 'source', 'prompt': '用哪份材料？', 'type': 'text'}])
    await finish_waiting(context)
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'nodeExecution': {'scope': 's', 'nodes': [{'id': 'q', 'scope': 's', 'kind': 'tool', 'label': '等待用户回答', 'state': 'awaiting_input', 'attempts': 1, 'output': {'content': json.dumps(question)}}]}}
        source = await db.get(Message, sent['messageId'])
        source.text = ''
        source.transcript_revision += 1
        await expire(db, message_ids=[source.id])
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['job']['state'] == 'cancelled' and message['job']['phase'] == 'cancelled'
    assert message['job']['nodes'][0]['state'] == 'cancelled'
    assert message['job']['taskOutcome']['nextAction'] == 'none'
    assert message['interactions'][0]['state'] == 'expired' and message['interactions'][0]['questions'] == []
