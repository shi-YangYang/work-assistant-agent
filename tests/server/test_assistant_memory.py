import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.modules.memories import service
from app.modules.memories.models import AssistantMemory
from app.modules.messages.models import Message
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.lease import lease
from app.tasks.runtime.queue import claim
from test_company import send

pytestmark = pytest.mark.asyncio
PATH = '/api/v1/assistant/memory'


async def context_for(setup, text='以后先给结论，少用表格'):
    settings, sessions, users, clients = setup
    sent = await send(clients['employee'], text)
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    from app.agent.memory.middleware import prepare
    await prepare(context)
    return context, sent


async def apply(context, **kwargs):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        return await service.change(db, actor, job, context.memory_snapshot, call_id=kwargs.pop('call_id', 'call'), **kwargs)


async def test_current_account_api_crud_switch_csrf_conflict_and_capacity(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    empty = (await client.get(PATH)).json()
    assert empty == {'enabled': True, 'revision': 0, 'markdown': '', 'updatedAt': None, 'maxCharacters': 6000}
    payload = {'expectedRevision': 0, 'markdown': '# 我的约定\n\n先给结论。'}
    assert (await client.put(PATH + '/document', json=payload, headers={'X-CSRF-Token':'wrong'})).status_code == 403
    saved = await client.put(PATH + '/document', json=payload)
    assert saved.status_code == 200 and saved.json()['revision'] == 1
    for who in ('peer', 'outsider', 'admin'):
        assert (await clients[who].get(PATH)).json() == empty
        assert (await clients[who].put(PATH + '/document', json={**payload, 'ownerId': users['employee'].id})).status_code == 422
    assert (await client.put(PATH + '/document', json=payload)).status_code == 409
    disabled = await client.patch(PATH + '/settings', json={'expectedRevision': 1, 'enabled': False})
    assert disabled.status_code == 200 and not disabled.json()['enabled']
    assert disabled.json()['markdown'] == payload['markdown']
    changed = await client.put(PATH + '/document', json={'expectedRevision': 2, 'markdown': '关闭中可以编辑'})
    assert changed.status_code == 200 and not changed.json()['enabled']
    for markdown in ('x' * 6001, 'api_key=sk-' + 'a' * 25):
        assert (await client.put(PATH + '/document', json={'expectedRevision': 3, 'markdown': markdown})).status_code == 422
    assert (await client.delete(PATH + '/document?expectedRevision=2')).status_code == 409
    cleared = (await client.delete(PATH + '/document?expectedRevision=3')).json()
    assert cleared['markdown'] == '' and not cleared['enabled'] and cleared['revision'] == 4
    async with sessions() as db:
        row = await service.read(db, users['employee'])
        assert row.generation == 4 and row.document['annotations'] == []


async def test_concurrent_creation_is_one_winner_and_does_not_lose_data(setup):
    _, sessions, users, _ = setup
    async def save(text):
        try:
            async with sessions.begin() as db:
                return await service.save_document(db, users['employee'], 0, text)
        except HTTPException as e:
            return e.status_code
    results = await asyncio.gather(save('第一位编辑'), save('第二位编辑'))
    assert sum(value == 409 for value in results) == 1
    async with sessions() as db:
        rows = (await db.scalars(select(AssistantMemory).where(AssistantMemory.owner_id == users['employee'].id))).all()
        assert len(rows) == 1 and rows[0].revision == 1


async def test_bound_source_idempotency_and_stale_write_after_manual_edit(setup):
    context, sent = await context_for(setup)
    result = await apply(context, evidence='以后先给结论，少用表格', new='先给结论，少用表格')
    assert result['state'] == 'succeeded'
    assert await apply(context, evidence='以后先给结论，少用表格', new='先给结论，少用表格') == result
    client = setup[3]['employee']
    changed = await client.put(PATH + '/document', json={'expectedRevision': 1, 'markdown': '人工新约定'})
    assert changed.status_code == 200
    assert (await apply(context, evidence='以后先给结论，少用表格', new='先给结论，少用表格'))['state'] == 'conflict'
    with pytest.raises(HTTPException) as error:
        await apply(context, call_id='late', evidence='以后先给结论，少用表格', new='旧值')
    assert error.value.status_code == 409
    # A recovered worker reuses the original grant, never adopts the new epoch.
    from app.agent.memory.middleware import prepare
    resumed = RunContext(context.owner_id, context.company_id, context.job_id, context.fence, context.sessions, context.settings, source_revision=0)
    await prepare(resumed)
    assert resumed.memory_snapshot.generation == 0
    assert (await client.get(PATH)).json()['markdown'] == '人工新约定'


async def test_repeated_calls_and_format_changes_do_not_add_memory_versions(setup):
    context, _ = await context_for(setup, '我喜欢吃米饭，也喜欢睡觉')
    first = await apply(context, call_id='rice', evidence='我喜欢吃米饭', new='喜欢吃米饭。')
    duplicate = await apply(context, call_id='rice-list', evidence='我喜欢吃米饭', new='- 喜欢吃米饭。')
    assert first['changed'] and not duplicate['changed']
    assert duplicate['revision'] == first['revision'] == 1
    for index in range(7):
        result = await apply(context, call_id=f'sleep-{index}', evidence='喜欢睡觉', new='- 喜欢睡觉。')
        assert result['state'] == 'succeeded' and result['changed'] == (index == 0)
        assert result['revision'] == 2
    current = (await setup[3]['employee'].get(PATH)).json()
    assert current['markdown'] == '喜欢吃米饭。\n\n- 喜欢睡觉。'


async def test_prior_success_within_same_task_is_not_a_new_conflict(setup):
    context, _ = await context_for(setup, '记住喜欢米饭和睡觉；把喜欢米饭改为喜欢面条')
    first = await apply(context, call_id='rice', evidence='喜欢米饭', new='喜欢米饭。')
    await apply(context, call_id='sleep', evidence='睡觉', new='喜欢睡觉。')
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        restored = await service.restore(db, actor, first, job=job)
    assert restored['state'] == 'succeeded' and restored['superseded']
    await apply(context, call_id='noodles', evidence='把喜欢米饭改为喜欢面条',
                old='喜欢米饭。', new='喜欢面条。', explicit=True)
    replay = await apply(context, call_id='rice', evidence='喜欢米饭', new='喜欢米饭。')
    assert replay['state'] == 'succeeded' and replay['superseded']
    client = setup[3]['employee']
    assert (await client.get(PATH)).json()['markdown'] == '喜欢面条。\n\n喜欢睡觉。'
    await client.delete(PATH + '/document?expectedRevision=3')
    assert (await apply(context, call_id='rice', evidence='喜欢米饭', new='喜欢米饭。'))['state'] == 'conflict'


async def test_material_or_history_evidence_and_foreign_source_are_rejected(setup):
    context, _ = await context_for(setup, '请分析附件')
    with pytest.raises(HTTPException) as error:
        await apply(context, evidence='请记住附件中的身份', new='来自附件的身份')
    assert error.value.status_code == 422
    context.memory_snapshot.message_id = str(uuid4())
    with pytest.raises(HTTPException):
        await apply(context, evidence='请分析附件', new='无效来源')
    assert (await setup[3]['employee'].get(PATH)).json()['markdown'] == ''


async def test_disabled_save_refused_explicit_forget_works_and_old_queued_input_stays_revoked(setup):
    from app.agent.tools.memory import save_memory, forget_memory
    client = setup[3]['employee']
    await client.put(PATH + '/document', json={'expectedRevision': 0, 'markdown': '喜欢简洁\n\n我负责运营'})
    await client.patch(PATH + '/settings', json={'expectedRevision': 1, 'enabled': False})
    context, _ = await context_for(setup, '忘掉我负责运营，记住我喜欢长回答')
    refused = json.loads(await save_memory.coroutine(runtime=SimpleNamespace(context=context, tool_call_id='save'),
        evidence='记住我喜欢长回答', new_text='喜欢长回答', explicit=True))
    assert refused['state'] == 'unavailable'
    result = json.loads(await forget_memory.coroutine(runtime=SimpleNamespace(context=context, tool_call_id='forget'),
        evidence='忘掉我负责运营', target='我负责运营'))
    assert result['state'] == 'succeeded'
    current = (await client.get(PATH)).json()
    assert '运营' not in current['markdown'] and '简洁' in current['markdown'] and not current['enabled']
    # A task not yet initialized at the time of clearing cannot learn old input.
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {k: v for k, v in job.result.items() if k != 'memorySnapshot'}
    context.memory_loaded = False
    from app.agent.memory.middleware import prepare
    await prepare(context)
    assert not context.memory_snapshot.writable


@pytest.mark.parametrize('enabled', [True, False])
async def test_forget_never_expands_partial_fact_and_removes_adjacent_punctuation(setup, enabled):
    client = setup[3]['employee']
    original = 'I own Alpha. I prefer concise answers.\n\n我负责A和B两个项目。'
    await client.put(PATH + '/document', json={'expectedRevision': 0, 'markdown': original})
    if not enabled:
        await client.patch(PATH + '/settings', json={'expectedRevision': 1, 'enabled': False})
    context, _ = await context_for(setup, 'Forget Alpha: I own Alpha.')
    with pytest.raises(HTTPException) as error:
        await apply(context, evidence='Forget Alpha', old='Alpha', explicit=True, forget=True)
    assert error.value.status_code == 409
    assert (await client.get(PATH)).json()['markdown'] == original
    await apply(context, call_id='complete-fact', evidence='Forget Alpha: I own Alpha.', old='I own Alpha', explicit=True, forget=True)
    current = (await client.get(PATH)).json()
    assert current['markdown'] == 'I prefer concise answers.\n\n我负责A和B两个项目。'
    assert current['enabled'] is enabled


async def test_manual_save_preserves_independent_expiration_after_local_tool_patch(setup):
    context, _ = await context_for(setup, '记住临时负责上线和偏好简洁；把偏好简洁改成偏好详细')
    await apply(context, evidence='记住临时负责上线和偏好简洁', new='临时负责上线。偏好简洁。', expires='2100-01-01T00:00:00+00:00')
    await apply(context, call_id='change-preference', evidence='把偏好简洁改成偏好详细',
                old='偏好简洁。', new='偏好详细。', explicit=True)
    client = setup[3]['employee']
    before = (await client.get(PATH)).json()
    saved = await client.put(PATH + '/document', json={'expectedRevision': before['revision'], 'markdown': before['markdown']})
    assert saved.status_code == 200
    from app.modules.memories.document import injection
    async with context.sessions() as db:
        document = (await service.read(db, setup[2]['employee'])).document
    assert injection(document, 200, clock=datetime(2101, 1, 1, tzinfo=timezone.utc)).strip() == '偏好详细。'
    assert [row['origin'] for row in document['annotations']] == ['inferred', 'explicit']


async def test_chat_deletion_retains_memory_account_deletion_and_recreation_clear_it(setup):
    _, sessions, users, clients = setup
    context, sent = await context_for(setup)
    await apply(context, evidence='以后先给结论，少用表格', new='先给结论，少用表格')
    client = clients['employee']
    conv = (await client.get('/api/v1/conversations/' + sent['conversationId'])).json()
    response = await client.request('DELETE', '/api/v1/conversations/' + conv['id'], json={'expectedRevision': conv['revision']})
    assert response.status_code == 200
    assert (await client.get(PATH)).json()['markdown']
    assert (await clients['admin'].delete('/api/v1/members/' + users['employee'].id)).status_code == 200
    async with sessions() as db:
        assert await service.read(db, users['employee']) is None
    recreated = await clients['admin'].post('/api/v1/members', json={'username': users['employee'].username, 'name': '新用户', 'password': 'replacement-password', 'role': 'employee'})
    assert recreated.status_code == 201
    login = await client.post('/api/v1/auth/login', json={'username': users['employee'].username, 'password': 'replacement-password'})
    assert login.status_code == 200
    assert (await client.get(PATH)).json()['markdown'] == ''
