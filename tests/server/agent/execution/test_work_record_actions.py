"""Typed work commands honor execution modes, receipts and local edits."""
import pytest
from app.agent.actions.operations import execute
from _support.agent.execution_permissions import mode_runtime
from _support.agent.business_actions import read_work
from _support.agent.work_execution_history import WorkJudge
from _support.work.work_records import create, body, key

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('changed', ['', 'content', 'sources', 'dependency'])
async def test_committed_progress_replay_accepts_only_its_own_version_advance(setup, changed):
    from dataclasses import replace
    from sqlalchemy import select
    from app.modules.operations.models import BusinessAction
    from app.tasks.feedback.outcomes import derive
    from app.tasks.models import Job
    from _support.agent.conversation_task_state import close_task
    _, sessions, _, clients = setup
    work = await create(clients['employee'])
    context, _ = await mode_runtime(setup, 'auto', '追加客户确认首页初稿，保存一次，再给两条验收建议')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1,
            'changes': {'update': {'action': 'create', 'text': '客户确认首页初稿'}}}
    original = await execute(context, **args)
    assert original['state'] == 'succeeded'
    # A restarted provider plans the same operation using its committed revision.
    restored = replace(context, intent_model=WorkJudge(), read_versions={})
    retry = {**args, 'expected_revision': original['objectRevision']}
    if changed == 'content':
        retry['changes'] = {'update': {'action': 'create', 'text': '客户确认上线'}}
    elif changed == 'sources':
        retry['source_tokens'] = ['unread-source']
    elif changed == 'dependency':
        retry.update(step=2, requires_step=1)
    result = await execute(restored, **retry)
    assert result['state'] == ('conflict' if changed else 'succeeded'), result
    if not changed:
        assert result['id'] == original['id']
        await close_task(restored)
        async with sessions() as db:
            job = await db.get(Job, context.job_id)
            assert not job.result['operationFeedback']
            assert all(item['category'] == 'success' for item in job.result['toolOutcomes'])
            assert derive(job, [result])['state'] == 'completed'
    else:
        assert result['existingOperation']['id'] == original['id']
    assert not restored.intent_model.inputs
    async with sessions() as db:
        assert len((await db.scalars(select(BusinessAction).where(BusinessAction.message_id == original['messageId']))).all()) == 1
    detail = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    updates = (await clients['employee'].get('/api/v1/work-items/' + work['id'] + '/updates')).json()['items']
    assert detail['revision'] == 2 and detail['body'] == work['body']
    assert len(updates) == 1 and updates[0]['text'] == '客户确认首页初稿'


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_progress_actions_modes_confirm_and_replay_without_replacing_body(setup, mode):
    *_, clients = setup
    work = await create(clients['employee'])
    context, _ = await mode_runtime(setup, mode, '记一条进展：客户已确认配色，保持其他内容不变')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1, 'changes': {'update': {'action': 'create', 'text': '客户已确认配色'}}}
    result = await execute(context, **args)
    assert result['state'] == ('pending' if mode == 'ask' else 'succeeded'), result
    if mode == 'ask':
        confirmed = await clients['employee'].post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()['state'] == 'succeeded'
    else:
        repeated = await execute(context, **args)
        assert repeated['id'] == result['id'] and repeated['state'] == 'succeeded'
    detail = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert detail['revision'] == 2 and detail['body'] == work['body']
    updates = (await clients['employee'].get('/api/v1/work-items/' + work['id'] + '/updates')).json()['items']
    assert len(updates) == 1 and updates[0]['text'] == '客户已确认配色'
    assert updates[0]['origin'] == ('assistant_confirmed' if mode == 'ask' else 'assistant')


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
@pytest.mark.parametrize('kind', ['update', 'material'])
async def test_typed_deletion_modes_confirm_and_replay(setup, mode, kind):
    from app.agent.actions.interactions import finish_waiting
    from _support.materials.documents import upload
    from app.modules.work.models import WorkMaterial, WorkUpdate
    _, sessions, _, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    context, _ = await mode_runtime(setup, mode, '删除刚才误记的进展，保留工作' if kind == 'update' else '移除刚才的材料，保留工作')
    context.intent_model = WorkJudge()
    if kind == 'update':
        saved = await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '误记的进展'}, headers=key())
        identifier = saved.json()['update']['id']
        changes = {'update': {'action': 'delete', 'id': identifier, 'expectedRevision': 1}}
    else:
        attachment = await upload(client, 'unused.txt', b'unused reference', 'text/plain')
        saved = await client.post(path + '/materials', json={'expectedRevision': 1, 'materials': [{'attachmentId': attachment['id']}]}, headers=key())
        identifier = saved.json()['materialIds'][0]
        changes = {'removeMaterial': {'id': identifier, 'expectedRevision': 1}}
    assert saved.status_code == 201, saved.text
    await read_work(context, work['id'])
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 2, 'changes': changes}
    result = await execute(context, **args)
    assert result['state'] == ('succeeded' if mode == 'full' else 'pending'), result
    assert context.intent_model.inputs[0]['proposedOperation']['effect'] == ('save' if mode == 'full' else 'prepare_confirmation')
    async with sessions() as db:
        row = await db.get(WorkUpdate if kind == 'update' else WorkMaterial, identifier)
        assert (row.deleted if kind == 'update' else row.removed) is (mode == 'full')
    repeated = await execute(context, **args)
    assert repeated['id'] == result['id'] and repeated['state'] == result['state']
    if mode != 'full':
        assert await finish_waiting(context)
        url = '/api/v1/business-actions/' + result['id'] + '/confirm'
        confirmed = await client.post(url, json={'expectedRevision': result['revision']})
        assert confirmed.status_code == 200 and confirmed.json()['state'] == 'succeeded', confirmed.text
        assert confirmed.json()['continuation']
        replayed = await client.post(url, json={'expectedRevision': result['revision']})
        assert replayed.json() == confirmed.json()
    after = (await client.get(path)).json()
    assert after['revision'] == 3 and after['body'] == work['body'] and after['status'] == work['status']
    async with sessions() as db:
        row = await db.get(WorkUpdate if kind == 'update' else WorkMaterial, identifier)
        assert row.revision == 2 and (row.deleted if kind == 'update' else row.removed)


async def test_body_creation_without_model_block_ids_has_stable_approval_and_replay(setup):
    *_, clients = setup
    context, _ = await mode_runtime(setup, 'ask', '创建官网工作并保存方案：先做移动端')
    context.intent_model = WorkJudge()
    document = {'schemaVersion': 1, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '先做移动端'}]}]}
    result = await execute(context, step=1, action='create_work', changes={'title': '官网', 'body': document})
    assert result['state'] == 'pending', result
    response = await clients['employee'].post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
    assert response.status_code == 200, response.text
    work = (await clients['employee'].get('/api/v1/work-items/' + response.json()['objectId'])).json()
    assert work['bodyText'] == '先做移动端' and work['summary'] == ''


async def test_local_body_edit_keeps_other_blocks_and_progress(setup):
    *_, clients = setup
    document = body('目标')
    document['content'].append({'type': 'paragraph', 'attrs': {'id': 'keep'}, 'content': [{'type': 'text', 'text': '保留原细节'}]})
    work = await create(clients['employee'], body=document)
    context, _ = await mode_runtime(setup, 'full', '把第一段改为新目标，其他部分不动')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'bodyEdits': [{'action': 'replace', 'blockId': 'first', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '新目标'}]}]}]})
    assert result['state'] == 'succeeded', result
    current = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert current['body']['content'][1] == work['body']['content'][1]
    assert current['bodyText'] == '新目标\n保留原细节' and current['summary'] == ''


async def test_body_edit_approval_resolves_original_and_normalized_replacement_blocks(setup):
    *_, clients = setup
    document = body('原第一段')
    document['content'].append({'type': 'paragraph', 'attrs': {'id': 'second'}, 'content': [{'type': 'text', 'text': '待删除第二段'}]})
    work = await create(clients['employee'], body=document)
    context, _ = await mode_runtime(setup, 'ask', '第一段改成新内容，并删除第二段，请先让我确认')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'bodyEdits': [{'action': 'replace', 'blockId': 'first', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '新内容'}]}]}, {'action': 'remove', 'blockId': 'second'}]})
    assert result['state'] == 'pending', result
    replace, remove = result['preview']['changes']['bodyEdits']
    assert replace['before'] == [work['body']['content'][0]]
    assert replace['blocks'][0]['attrs']['id'] == 'first'
    assert replace['blocks'][0]['content'][0]['text'] == '新内容'
    assert remove['before'] == [work['body']['content'][1]] and remove['blocks'] == []
    assert (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()['body'] == work['body']


@pytest.mark.parametrize('entrypoint', ['agent', 'legacy'])
@pytest.mark.parametrize('changes', [{'status': 'done'}, {'dueDate': '2026-10-08'}])
async def test_property_only_writes_are_today_facts_without_repeating_yesterday_progress(setup, entrypoint, changes):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.modules.reports.models import Report
    from app.modules.reports.generation.sources import report_inputs, report_source_content, sources_for
    from app.modules.work.models import WorkRevision, WorkUpdate
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    progress = await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '昨天完成需求核对'}, headers=key())
    assert progress.status_code == 201, progress.text
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    async with sessions.begin() as db:
        for revision in (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == work['id']))).all():
            revision.created_at = stamp - timedelta(days=1)
        update = await db.get(WorkUpdate, progress.json()['update']['id'])
        update.created_at = stamp - timedelta(days=1)
    if entrypoint == 'agent':
        context, _ = await mode_runtime(setup, 'full', '只修改这项工作的状态或截止日期，保留其他内容')
        context.intent_model = WorkJudge()
        await read_work(context, work['id'])
        result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=2, changes=changes)
        assert result['state'] == 'succeeded', result
    else:
        result = await client.post(path + '/progress', json={'expectedRevision': 2, 'title': work['title'], 'summary': '昨天完成需求核对', **changes})
        assert result.status_code == 200, result.text
    async with sessions.begin() as db:
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id'], WorkRevision.revision == 3))
        revision.created_at = stamp
        await db.flush()
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='weekly', period=stamp.date().isoformat(), period_end=stamp.date().isoformat(), timezone='UTC')
        sources = await report_inputs(db, report)
        assert [source.id for source in sources] == [revision.id]
        fact = report_source_content(sources[0])
        assert fact['factType'] == 'attribute_change' and fact['summary'] == ''
        assert all(fact[field] == value for field, value in changes.items())
        assert revision.content['summary'] == '昨天完成需求核对'
        assert revision.content['body'] == work['body']
        assert await sources_for(db, report, users['employee'], [revision.id]) == sources
        updates = (await db.scalars(select(WorkUpdate).where(WorkUpdate.work_id == work['id']))).all()
        assert len(updates) == 1 and updates[0].text == '昨天完成需求核对'


async def test_unchanged_progress_receipt_keeps_original_snapshot_after_newer_progress(setup):
    from app.agent.completion.evidence.work_receipts import work_record_evidence
    from app.modules.operations.receipts import receipt_summary
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    first = (await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '客户确认首页初稿'}, headers=key())).json()['update']
    await client.post(path + '/updates', json={'expectedRevision': 2, 'text': '客户确认上线'}, headers=key())
    context, _ = await mode_runtime(setup, 'full', '把第一条进展更正为客户确认首页初稿，其他内容保持不变')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=3,
                           changes={'update': {'action': 'edit', 'id': first['id'], 'expectedRevision': 1, 'text': first['text']}})
    assert result['state'] == 'succeeded', result
    assert result['unchanged'] and result['changedFields'] == []
    assert result['satisfiedFields'] == ['update']
    from types import SimpleNamespace
    from app.tasks.feedback.work_requirements import uncovered
    requirement = {'fields': {'update': {'revision': 3, 'excludedReceipts': []}}}
    assert not uncovered(SimpleNamespace(target_id=result['messageId'], result={}), work['id'], requirement, [result])
    assert result['objectRevision'] == 3 and result['updateWorkRevision'] == 2
    assert '内容未变化，已保留原记录' in receipt_summary([result])
    async with sessions() as db:
        evidence = await work_record_evidence(db, users['employee'], [result])
        assert evidence[0]['unchanged']
        assert evidence[0]['progressUpdate']['text'] == first['text']
    detail = (await client.get(path)).json()
    assert detail['revision'] == 3 and detail['summary'] == '客户确认上线'
