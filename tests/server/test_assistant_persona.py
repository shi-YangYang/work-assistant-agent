"""Persona persistence, isolation and retry boundaries; no provider network IO."""
import asyncio
import hashlib
import json
from zoneinfo import ZoneInfo
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.agent.reply_review import REVIEW_VERSION
from app.core.config import Settings
from app.db.idempotency import Idempotency
from app.modules.conversations.models import Conversation
from app.modules.members.models import Company, Member
from app.modules.messages.models import Message
from app.tasks.handlers import process_job
from app.tasks.models import Job
from app.tasks.queue import claim
from test_company import keyed
from test_model_services import create, payload, route
from test_task_retry import fast_nodes


def test_migration_preserves_history_and_separates_new_defaults(monkeypatch):
    Settings()
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'persona_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'apps/server/app/migrations'))
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0014_voiceprint_cleanup')
        with scoped.begin() as connection:
            company_id = connection.execute(Company.__table__.insert().values(name='人设迁移公司').returning(Company.id)).scalar_one()
            owner_id = connection.execute(Member.__table__.insert().values(company_id=company_id, username='persona_migration', name='原有成员', password_hash='unchanged').returning(Member.id)).scalar_one()
            old_conversation = Table('company_conversation', MetaData(), autoload_with=connection)
            old_message = Table('company_message', MetaData(), autoload_with=connection)
            conversation_values = {column.name: column.default.arg(None) if column.default.is_callable else column.default.arg for column in Conversation.__table__.columns if column.default and column.name in old_conversation.c}
            conversation_values.update(company_id=company_id, owner_id=owner_id, title='保留原会话')
            connection.execute(old_conversation.insert().values(**conversation_values))
            message_values = {column.name: column.default.arg(None) if column.default.is_callable else column.default.arg for column in Message.__table__.columns if column.default and column.name in old_message.c}
            message_values.update(company_id=company_id, owner_id=owner_id, conversation_id=conversation_values['id'], text='旧消息', reply='原答复')
            connection.execute(old_message.insert().values(**message_values))
            before_conversation = dict(connection.execute(select(old_conversation)).mappings().one())
            before_message = dict(connection.execute(select(old_message)).mappings().one())
        command.upgrade(config, 'head')
        with scoped.begin() as connection:
            assert dict(connection.execute(select(Conversation.__table__)).mappings().one()) == {**before_conversation, 'persona_id': 'professional'}
            assert dict(connection.execute(select(Message.__table__)).mappings().one()) == {**before_message, 'persona_id': 'professional', 'private_context': False, 'deliverable_reference': {}}
            # New application-created conversations differ from historical backfills.
            fresh = connection.execute(Conversation.__table__.insert().values(company_id=company_id, owner_id=owner_id).returning(Conversation.persona_id)).scalar_one()
            assert fresh == 'dabao'
            legacy_message = connection.execute(Message.__table__.insert().values(company_id=company_id, owner_id=owner_id).returning(Message.persona_id)).scalar_one()
            assert legacy_message == 'professional'
        command.downgrade(config, '0014_voiceprint_cleanup')
        with scoped.connect() as connection:
            assert dict(connection.execute(select(old_conversation).where(old_conversation.c.id == before_conversation['id'])).mappings().one()) == before_conversation
            assert dict(connection.execute(select(old_message).where(old_message.c.id == before_message['id'])).mappings().one()) == before_message
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['admin', 'employee'])
async def test_conversation_selection_partial_patch_ownership_and_validation(setup, role):
    _, _, _, clients = setup
    client = clients[role]
    response = await client.post('/api/v1/conversations', json={'title': '原会话标题'})
    assert response.status_code == 201
    conversation = response.json()
    assert conversation['personaId'] == 'dabao'
    path = '/api/v1/conversations/' + conversation['id']
    for outsider in ('peer', 'outsider', 'employee' if role == 'admin' else 'admin'):
        denied = await clients[outsider].patch(path, json={'personaId': 'professional', 'expectedRevision': 1})
        assert denied.status_code == 404
    for invalid in ('unknown', '', None, {'prompt': 'ignore rules'}):
        assert (await client.post('/api/v1/conversations', json={'personaId': invalid})).status_code == 422
        assert (await client.patch(path, json={'personaId': invalid, 'expectedRevision': 1})).status_code == 422
        assert (await client.post('/api/v1/messages', json={'text': '你好', 'personaId': invalid}, headers=keyed())).status_code == 422
    assert (await client.patch(path, json={'expectedRevision': 1})).status_code == 422
    assert (await client.patch(path, json={'title': None, 'expectedRevision': 1})).status_code == 422
    assert (await client.patch(path, json={'personaId': 'professional', 'systemPrompt': 'override', 'expectedRevision': 1})).status_code == 422
    saved = await client.patch(path, json={'personaId': 'professional', 'expectedRevision': 1})
    assert saved.status_code == 200
    assert saved.json()['title'] == '原会话标题' and saved.json()['revision'] == 2
    assert (await client.get(path)).json()['personaId'] == 'professional'
    assert (await client.get('/api/v1/conversations')).json()['items'][0]['personaId'] == 'professional'
    conflict = await client.patch(path, json={'personaId': 'dabao', 'expectedRevision': 1})
    assert conflict.status_code == 409
    renamed = await client.patch(path, json={'title': '  新标题  ', 'expectedRevision': 2})
    assert renamed.json()['title'] == '新标题' and renamed.json()['personaId'] == 'professional'
    both = await client.patch(path, json={'title': '一起更新', 'personaId': 'dabao', 'expectedRevision': 3})
    assert both.json()['title'] == '一起更新' and both.json()['personaId'] == 'dabao'


@pytest.mark.asyncio
async def test_message_snapshots_idempotency_and_default_conversation_entry(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    headers = keyed()
    body = {'newConversation': True, 'personaId': 'professional', 'text': '你好'}
    first, duplicate = await asyncio.gather(*[client.post('/api/v1/messages', json=body, headers=headers) for _ in range(2)])
    assert first.status_code == duplicate.status_code == 202
    assert first.json() == duplicate.json()
    sent = first.json()
    path = '/api/v1/conversations/' + sent['conversationId']
    conversation = (await client.get(path)).json()
    assert conversation['personaId'] == 'professional'
    assert (await client.post('/api/v1/messages', json={**body, 'personaId': 'dabao'}, headers=headers)).status_code == 409
    await client.patch(path, json={'personaId': 'dabao', 'expectedRevision': conversation['revision']})
    assert (await client.post('/api/v1/messages', json=body, headers=headers)).json() == sent
    async with sessions.begin() as db:
        (await db.get(Job, sent['jobId'])).state = 'succeeded'
    omitted = await client.post('/api/v1/messages', json={'conversationId': sent['conversationId'], 'text': '沿用当前选择'}, headers=keyed())
    assert omitted.status_code == 202, omitted.text
    async with sessions.begin() as db:
        (await db.get(Job, omitted.json()['jobId'])).state = 'succeeded'
    explicit = await client.post('/api/v1/messages', json={'conversationId': sent['conversationId'], 'personaId': 'professional', 'text': '冻结明确选择'}, headers=keyed())
    assert explicit.status_code == 202, explicit.text
    assert (await client.get(path)).json()['personaId'] == 'dabao'
    async with sessions() as db:
        assert (await db.get(Message, sent['messageId'])).persona_id == 'professional'
        assert (await db.get(Message, omitted.json()['messageId'])).persona_id == 'dabao'
        assert (await db.get(Message, explicit.json()['messageId'])).persona_id == 'professional'
    # The old no-conversation route also initializes a new conversation correctly.
    default = await clients['peer'].post('/api/v1/messages', json={'text': '旧入口', 'personaId': 'professional'}, headers=keyed())
    assert default.status_code == 202
    assert (await clients['peer'].get('/api/v1/conversations/' + default.json()['conversationId'])).json()['personaId'] == 'professional'
    fresh = await client.post('/api/v1/messages', json={'newConversation': True, 'text': '默认新会话'}, headers=keyed())
    assert (await client.get('/api/v1/conversations/' + fresh.json()['conversationId'])).json()['personaId'] == 'dabao'
    # Seed the exact digest shape used before personaId/newConversation existed.
    legacy_headers = keyed()
    legacy_payload = {'conversationId': sent['conversationId'], 'text': '旧请求重放', 'attachmentIds': [], 'replyTo': None}
    legacy_digest = hashlib.sha256(json.dumps(legacy_payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    async with sessions.begin() as db:
        db.add(Idempotency(company_id=users['employee'].company_id, owner_id=users['employee'].id, action='message', key=legacy_headers['Idempotency-Key'], digest=legacy_digest, response=sent))
    replay = await client.post('/api/v1/messages', json=legacy_payload, headers=legacy_headers)
    assert replay.status_code == 202 and replay.json() == sent
    async with sessions() as db:
        assert len((await db.scalars(select(Message).where(Message.owner_id == users['employee'].id))).all()) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['admin', 'employee'])
@pytest.mark.parametrize('persona', ['dabao', 'professional'])
async def test_worker_freezes_persona_through_queue_auto_and_manual_retry(setup, monkeypatch, fast_nodes, role, persona):
    settings, sessions, users, clients = setup
    client = clients[role]
    service = await create(clients['admin'])
    routing = route(service)
    routing['assistant']['streaming'] = False
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=routing)).status_code == 200
    sent = (await client.post('/api/v1/messages', json={'newConversation': True, 'personaId': persona, 'text': '今天忙得脑子打结了'}, headers=keyed())).json()
    path = '/api/v1/conversations/' + sent['conversationId']
    conversation = (await client.get(path)).json()
    other = 'professional' if persona == 'dabao' else 'dabao'
    await client.patch(path, json={'personaId': other, 'expectedRevision': conversation['revision']})
    calls = []
    marker = '当前聊天风格是“大包人设”' if persona == 'dabao' else '当前聊天风格是“专业人设”'
    answer = '脑内标签页开太多了。先说最卡的一件，我们一件件拆。' if persona == 'dabao' else '先处理最卡的一件。现在是哪项任务？'
    async def response(request):
        body = json.loads(request.content)
        calls.append((str(request.url), body))
        system = '\n'.join(str(item['content']) for item in body['messages'] if item['role'] == 'system')
        if body.get('tools'):
            assert marker in system
            assert ('处理管理员本人工作和已授权员工业务问答' if role == 'admin' else '处理当前员工的工作请求') in system
            if len(calls) == 1:
                return httpx.Response(502, json={'error': {'message': 'controlled temporary error'}})
            message = {'role': 'assistant', 'content': answer}
        else:
            assert '当前聊天风格是' not in system
            assert '明显的比喻或自嘲' in system and '不能以玩笑' in system
            review = json.loads(body['messages'][-1]['content'])
            assert review['version'] == REVIEW_VERSION and review['toolEvidence'] == [] and review['currentActions'] == []
            if len(calls) == 3:
                return httpx.Response(401, json={'error': {'message': 'controlled review failure'}})
            message = {'role': 'assistant', 'content': json.dumps({'segments': [{'index': item['index'], 'scope_reason': '受控范围判定', 'scope': 'answer', 'kind': 'information', 'evidence': []} for item in review['segments']], 'needs_action': False})}
        return httpx.Response(200, json={'choices': [{'message': message, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    job = await claim(sessions, users[role].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver)
        failed = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
        assert failed['job']['state'] == 'awaiting_retry', failed
        assert len(calls) == 3
        # Retry retains message persona but deliberately uses the latest model binding.
        changed = await clients['admin'].patch('/api/v1/settings/model-services/' + service['id'], json={**payload(url='https://latest.example/v1'), 'apiKey': 'controlled-latest', 'expectedRevision': 1})
        assert changed.status_code == 200
        assert (await client.post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={})).status_code == 200
        retried = await claim(sessions, users[role].id)
        await process_job(retried, sessions, settings, saver)
    result = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['job']['state'] == 'awaiting_input' and result['reply'] == answer, result
    assert result['actions'] == [] and result['drafts'] == [] and result['suggestions'] == []
    assert len(calls) == 5 and all(url.startswith('https://latest.example/') for url, _ in calls[3:])
    async with sessions() as db:
        assert (await db.get(Message, sent['messageId'])).persona_id == persona
        assert (await db.get(Conversation, sent['conversationId'])).persona_id == other
        assert (await db.get(Job, sent['jobId'])).model_binding['assistant']['revision'] == 2
        threads = (await db.scalars(text('SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix': users[role].company_id + ':%'})).all()
        assert threads
        assert all((':persona:dabao:' in thread) == (persona == 'dabao') for thread in threads)
        assert not (await client.get('/api/v1/work-items')).json()['items']


@pytest.mark.asyncio
async def test_reply_scope_selection_rejects_old_cache_and_preserves_original_text(setup):
    from app.agent.reply_review import review_reply
    from app.core.digests import digest
    from test_business_actions import ReplyJudge, runtime
    context, _ = await runtime(setup, '只想把这件事说出来，不需要建议。')
    answer = '一直憋着这件事，确实很难受。你可以先列出处理它的步骤。'
    # Fixed labels exercise selection/cache behavior, not model understanding.
    judge = ReplyJudge(['information', 'information'], scopes=['answer', 'extra'])
    first = await review_reply(context, answer, model=judge)
    assert first.verified and first.text == '一直憋着这件事，确实很难受。'
    assert not first.needs_action and not first.execution_claims
    assert judge.inputs[0]['version'] == REVIEW_VERSION
    old_verdict = json.dumps({'segments': [{'index': row['index'], 'scope_reason': '受控范围判定', 'scope': 'answer', 'kind': 'information'} for row in judge.inputs[0]['segments']]})
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'replyReview': {'digest': digest({**judge.inputs[0], 'version': REVIEW_VERSION - 1}), 'verdict': old_verdict}}
    second = await review_reply(context, answer, model=judge)
    assert second == first and len(judge.inputs) == 2
    # Even a cache entry with the new digest must carry the new required schema.
    missing_scope = json.dumps({'segments': [{'index': row['index'], 'kind': 'information'} for row in judge.inputs[0]['segments']]})
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'replyReview': {'digest': digest(judge.inputs[0]), 'verdict': missing_scope}}
    recovered = await review_reply(context, answer, model=judge)
    cached = await review_reply(context, answer, model=judge)
    assert recovered == cached == first and len(judge.inputs) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('extra_kind', ['information', 'query_fact', 'unsupported'])
async def test_reply_scope_selection_does_not_trigger_query_fallback(setup, extra_kind):
    from types import SimpleNamespace
    from app.agent.reply_review import check_segments
    from app.agent.tools.work import find_work_items
    from test_business_actions import runtime
    context, _ = await runtime(setup, '只想说说，不需要建议。')
    result = await find_work_items.coroutine('', SimpleNamespace(context=context), status='blocked')
    evidence = [{'id': 2, 'tool': 'find_work_items', 'result': result}]
    parts = ['这件事确实让你很为难。', '先把回复留到明天。']
    verdict = {'segments': [{'index': 0, 'scope_reason': '受控范围判定', 'scope': 'answer', 'kind': 'information'}, {'index': 1, 'scope_reason': '无关建议', 'scope': 'extra', 'kind': extra_kind}]}
    reviewed = check_segments(parts, json.dumps(verdict), evidence)
    assert reviewed.verified and reviewed.text == parts[0] and not reviewed.dropped_query
    verdict['segments'][1].update(scope='answer', kind='unsupported')
    rejected_fact = check_segments([parts[0], '查到三项受阻的工作。'], json.dumps(verdict), evidence)
    assert rejected_fact.verified and rejected_fact.text == parts[0] and rejected_fact.dropped_query


@pytest.mark.parametrize('changes', [
    {'scope': None}, {'scope': 'unknown'}, {'scope_reason': None},
    {'scope_reason': '   '}, {'scope_reason': 'x' * 81}, {'kind': 'out_of_scope'},
])
def test_review_rejects_missing_or_invalid_scope(changes):
    from app.agent.reply_review import ReviewFormatError, check_segments
    row = {'index': 0, 'scope_reason': '直接回答当前问题', 'scope': 'answer', 'kind': 'information'}
    for key, value in changes.items():
        if value is None:
            row.pop(key)
        else:
            row[key] = value
    with pytest.raises(ReviewFormatError, match='Invalid review schema'):
        check_segments(['受控答复。'], json.dumps({'segments': [row]}), [])


def test_necessary_scope_preserves_structure_without_bypassing_fact_checks():
    from app.agent.reply_review import check_segments, reply_segments
    answer = '操作步骤：\n1. 打开设置。\n2. 修改选项。\n\n来源：工作甲，当前状态为进行中。\n\n还有一个未询问的字段。'
    parts = reply_segments(answer)
    assert len(parts) == 3 and '2. 修改选项。' in parts[0]
    evidence = [{'id': 7, 'tool': 'get_work_item', 'result': '{"title":"工作甲","status":"in_progress"}'}]
    rows = [
        {'index': 0, 'scope_reason': '完成当前任务所需的步骤', 'scope': 'answer', 'kind': 'information'},
        {'index': 1, 'scope_reason': '唯一来源定位', 'scope': 'necessary', 'supports': [0], 'kind': 'query_fact', 'evidence': [7]},
        {'index': 2, 'scope_reason': '未询问的独立字段', 'scope': 'extra', 'kind': 'query_fact', 'evidence': [7]},
    ]
    kept = check_segments(parts, json.dumps({'segments': rows}), evidence)
    assert kept.text == ''.join(parts[:2]).strip() and not kept.dropped_query
    rows[1]['evidence'] = [999]
    rejected = check_segments(parts, json.dumps({'segments': rows}), evidence)
    assert rejected.text == parts[0].strip() and rejected.dropped_query
    rows[2].update(kind='execution', evidence=[])
    actual_execution = check_segments(parts, json.dumps({'segments': rows}), evidence)
    assert actual_execution.execution_claims and actual_execution.text == rejected.text


def test_necessary_segments_follow_retained_answers_and_transitive_support():
    from app.agent.reply_review import check_segments
    parts = ['主路径。', '额外方案。', '额外方案前提。', '前提的补充。', '唯一来源。', '来源解释。', '两条路径共同需要的背景。']
    scopes = ['answer', 'extra', 'necessary', 'necessary', 'necessary', 'necessary', 'necessary']
    supports = [[], [], [1], [2], [0], [4], [1, 0]]
    rows = [{'index': i, 'scope_reason': '受控依赖', 'scope': scope, 'supports': supports[i], 'kind': 'information'} for i, scope in enumerate(scopes)]
    result = check_segments(parts, json.dumps({'segments': rows}), [])
    assert result.verified and result.text == ''.join(parts[i] for i in [0, 4, 5, 6])
    assert not result.dropped_query
    # A removed optional fact must not activate the query fallback either.
    rows[2].update(kind='query_fact', evidence=[999])
    evidence = [{'id': 7, 'tool': 'get_work_item', 'result': '{"title":"工作甲"}'}]
    result = check_segments(parts, json.dumps({'segments': rows}), evidence)
    assert result.text == ''.join(parts[i] for i in [0, 4, 5, 6]) and not result.dropped_query
    # A factually rejected answer removes all its support, even supported facts.
    rows[0].update(kind='query_fact', evidence=[999])
    rows[4].update(kind='query_fact', evidence=[7])
    rejected = check_segments(parts, json.dumps({'segments': rows}), evidence)
    assert rejected.text == '' and rejected.dropped_query


@pytest.mark.parametrize('scope,supports', [
    ('necessary', None), ('necessary', []), ('necessary', [0]),
    ('necessary', [2]), ('necessary', [-1]), ('necessary', [1, 1]),
    ('necessary', ['1']), ('necessary', [True]), ('answer', [1]),
])
def test_review_rejects_invalid_support_targets(scope, supports):
    from app.agent.reply_review import ReviewFormatError, check_segments
    rows = [
        {'index': 0, 'scope_reason': '受控依赖', 'scope': scope, 'kind': 'information'},
        {'index': 1, 'scope_reason': '直接回答', 'scope': 'answer', 'kind': 'information'},
    ]
    if supports is not None:
        rows[0]['supports'] = supports
    with pytest.raises(ReviewFormatError):
        check_segments(['说明。', '回答。'], json.dumps({'segments': rows}), [])


@pytest.mark.parametrize('reaches_answer', [False, True])
def test_review_rejects_support_cycles_even_when_another_edge_reaches_answer(reaches_answer):
    from app.agent.reply_review import ReviewFormatError, check_segments
    rows = [
        {'index': 0, 'scope_reason': '受控依赖', 'scope': 'necessary', 'supports': [1, 2] if reaches_answer else [1], 'kind': 'information'},
        {'index': 1, 'scope_reason': '受控依赖', 'scope': 'necessary', 'supports': [0], 'kind': 'information'},
        {'index': 2, 'scope_reason': '直接回答', 'scope': 'answer', 'kind': 'information'},
    ]
    with pytest.raises(ReviewFormatError, match='Cyclic support targets'):
        check_segments(['说明甲。', '说明乙。', '回答。'], json.dumps({'segments': rows}), [])


@pytest.mark.asyncio
async def test_persona_stays_out_of_authorization_and_report_generation(setup):
    from langchain_core.messages import AIMessage
    from app.agent.operations import execute
    from app.tasks.context import RunContext
    from test_business_actions import Judge, create as create_work, finish
    settings, sessions, users, clients = setup
    await create_work(clients['employee'], title='正式工作', summary='方案已整理', status='done')
    sent = (await clients['employee'].post('/api/v1/messages', json={'newConversation': True, 'personaId': 'dabao', 'text': '生成今天的正式日报'}, headers=keyed())).json()
    job = await claim(sessions, users['employee'].id)
    class CaptureJudge(Judge):
        async def ainvoke(self, messages):
            assert all('当前聊天风格是' not in str(message.content) for message in messages)
            return await super().ainvoke(messages)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, persona_id='dabao', source_revision=0, intent_model=CaptureJudge())
    from app.db.base import now
    result = await execute(context, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    assert result['state'] == 'running'
    assert context.intent_model.inputs and 'personaId' not in context.intent_model.inputs[0]
    await finish(context)
    prompts = []
    class Reporter:
        async def ainvoke(self, messages):
            prompts.append(messages)
            assert all('当前聊天风格是' not in str(message.content) for message in messages)
            data = json.loads(messages[-1].content)
            if data.get('task') == 'report_fact_review':
                return AIMessage(content='{"valid":true}')
            assert data['userRequest'] == '生成今天的正式日报'
            assert '幽默' not in data['userRequest'] and 'personaId' not in data
            return AIMessage(content=json.dumps({'completed': '方案已整理', 'ongoing': '', 'blockers': '', 'next': ''}))
    report_job = await claim(sessions, users['employee'].id)
    await process_job(report_job, sessions, settings, None, model=Reporter())
    report = (await clients['employee'].get('/api/v1/reports/' + result['objectId'])).json()
    assert report['content']['completed'] == '方案已整理'
    assert len(prompts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('persona', ['professional', 'dabao'])
async def test_legacy_checkpoint_identity_resumes_without_regenerating(monkeypatch, persona):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from langchain_core.messages import AIMessage
    from app.agent.harness import invoke_harness
    from app.core.digests import digest
    from app.db.base import now
    from app.tasks.context import RunContext
    from app.tasks.handlers import message_input_digest

    class Database:
        async def get(self, model, identifier):
            return SimpleNamespace(rules={'timezone': 'Asia/Shanghai'}) if model is Company else SimpleNamespace(created_at=now())
    @asynccontextmanager
    async def session():
        yield Database()
    class Sessions:
        begin = staticmethod(session)
        __call__ = staticmethod(session)
    job = SimpleNamespace(id='saved-job', kind='message', target_id='saved-message', access={'owner': 'member'})
    actor = SimpleNamespace(id='member', company_id='company', role='employee')
    blocks = [{'type': 'text', 'text': '旧输入'}]
    context = RunContext(actor.id, actor.company_id, job.id, 1, Sessions(), None, persona_id=persona, source_revision=3, document_snapshot='saved-files', node_retry=True)
    # Match the pre-persona input and scope formulas, including config identity.
    old_input = digest({'blocks': blocks, 'sourceRevision': 3, 'documents': 'saved-files', 'voiceCommandAttachmentId': None})
    current_input = message_input_digest(context, blocks, 3, None)
    assert (current_input == old_input) == (persona == 'professional')
    old_scope = digest({'input': old_input, 'config': None, 'configAttempt': 0, 'dataRevision': 0})
    context.node_scope = digest({'input': current_input, 'config': None, 'configAttempt': 0, 'dataRevision': 0})
    content_digest = hashlib.sha256(json.dumps(blocks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    old_thread = f'company:member:job:saved-job:scope:{old_scope}:input:3:{content_digest}:files:saved-files'
    saved_threads = []
    async def saved_state(config):
        thread = config['configurable']['thread_id']
        saved_threads.append(thread)
        assert (thread == old_thread) == (persona == 'professional')
        if persona == 'dabao':
            assert ':persona:dabao:' in thread
        return SimpleNamespace(values={'messages': [AIMessage(content='已有核对前答复')]}, next=())
    graph = SimpleNamespace(aget_state=saved_state, ainvoke=AsyncMock(side_effect=AssertionError('completed checkpoint must not regenerate')))
    monkeypatch.setattr('app.agent.harness.lease', AsyncMock(return_value=(job, actor)))
    monkeypatch.setattr('app.tasks.lease.lease', AsyncMock(return_value=(job, actor)))
    monkeypatch.setattr('app.agent.harness.conversation_history', AsyncMock(return_value=[]))
    monkeypatch.setattr('app.agent.harness.build_graph', lambda *args: graph)
    from langgraph.checkpoint.memory import InMemorySaver
    assert await invoke_harness(context, InMemorySaver(), blocks) == '已有核对前答复'
    assert len(saved_threads) == 1
    graph.ainvoke.assert_not_awaited()
