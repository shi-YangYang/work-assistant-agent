"""Work content, progress and metadata keep independent transactional meaning."""
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.modules.work.models import WorkItem, WorkUpdate, WorkUpdateRevision
from app.modules.reports.models import Report
from app.modules.reports.sources import report_inputs, report_source_content
from app.db.base import now

pytestmark = pytest.mark.asyncio


def key():
    return {'Idempotency-Key': str(uuid4())}


def body(text='目标与方案'):
    return {'schemaVersion': 1, 'content': [{'type': 'paragraph', 'attrs': {'id': 'first'}, 'content': [{'type': 'text', 'text': text}]}]}


async def create(client, **extra):
    response = await client.post('/api/v1/work-items', json={'title': '客户官网', 'body': body(), **extra}, headers=key())
    assert response.status_code == 201, response.text
    return response.json()


async def test_body_progress_metadata_and_legacy_preservation(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    assert work['revision'] == 1 and work['summary'] == ''
    path = '/api/v1/work-items/' + work['id']
    payload = {'expectedRevision': 1, 'text': '客户确认了初稿'}
    headers = key()
    response = await client.post(path + '/updates', json=payload, headers=headers)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['work']['body'] == work['body']
    assert result['work']['summary'] == payload['text']
    assert (await client.post(path + '/updates', json=payload, headers=headers)).json() == result
    patch = await client.patch(path, json={'expectedRevision': 2, 'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '第二阶段先做移动端'}]}]}]}, headers=key())
    assert patch.status_code == 200, patch.text
    changed = patch.json()['work']
    legacy = await client.post(path + '/progress', json={'expectedRevision': 3, 'title': work['title'], 'status': 'blocked'})
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()['body'] == changed['body']
    assert len((await client.get(path + '/updates')).json()['items']) == 1
    async with sessions() as db:
        rows = (await db.scalars(select(WorkUpdate).where(WorkUpdate.work_id == work['id']))).all()
        assert len(rows) == 1


async def test_update_edit_delete_and_historical_snapshot(setup):
    *_, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    result = (await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '周三开会'}, headers=key())).json()
    item = result['update']
    edited = await client.patch(path + '/updates/' + item['id'], json={'expectedRevision': 2, 'expectedUpdateRevision': 1, 'text': '周四开会'}, headers=key())
    assert edited.status_code == 200, edited.text
    assert (await client.get(path + '/updates?revision=2')).json()['items'][0]['text'] == '周三开会'
    assert (await client.get(path + '/updates')).json()['items'][0]['text'] == '周四开会'
    deleted = await client.request('DELETE', path + '/updates/' + item['id'], json={'expectedRevision': 3, 'expectedUpdateRevision': 2}, headers=key())
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()['work']['body'] == work['body']
    assert deleted.json()['work']['summary'] == ''
    assert (await client.get(path + '/updates')).json()['items'] == []


@pytest.mark.parametrize('invalid', [None, 'bad', {'type': 'doc'}, [{'type': 'paragraph', 'content': None}], [{'type': 'paragraph', 'marks': None}], [{'type': 'paragraph', 'attrs': []}], [{'type': 'paragraph', 'content': [{'type': 'material', 'attrs': {'materialId': 'x'}}]}], [{'type': 'script'}], *[[{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'link', 'marks': [{'type': 'link', 'attrs': attrs}]}]}] for attrs in (None, 'invalid', {'href': 'http://['}, {'href': 'javascript:alert(1)'})]])
async def test_invalid_document_is_422_and_preserves_saved_work(setup, invalid):
    *_, clients = setup
    client = clients['employee']
    work = await create(client)
    response = await client.patch('/api/v1/work-items/' + work['id'], json={'expectedRevision': 1, 'body': {'schemaVersion': 1, 'content': invalid}}, headers=key())
    assert response.status_code == 422, response.text
    detail = (await client.get('/api/v1/work-items/' + work['id'])).json()
    assert detail['revision'] == 1 and detail['body'] == work['body']


async def test_version_conflict_and_access_do_not_overwrite(setup):
    *_, clients = setup
    work = await create(clients['employee'])
    path = '/api/v1/work-items/' + work['id']
    assert (await clients['employee'].patch(path, json={'expectedRevision': 1, 'dueDate': '2026-10-08'}, headers=key())).status_code == 200
    for actor in ('peer', 'outsider', 'admin'):
        assert (await clients[actor].patch(path, json={'expectedRevision': 2, 'body': body('bad')}, headers=key())).status_code == 404
    assert (await clients['employee'].patch(path, json={'expectedRevision': 1, 'body': body('stale')}, headers=key())).status_code == 409
    assert (await clients['admin'].get(path)).status_code == 200
    assert (await clients['peer'].get(path)).status_code == 404
    detail = (await clients['employee'].get(path)).json()
    assert detail['body'] == work['body'] and detail['dueDate'] == '2026-10-08'


async def test_search_all_updates_and_reports_exclude_plans(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client, body=body('未来计划：下周上线'))
    path = '/api/v1/work-items/' + work['id']
    for index, text in enumerate(['客户确认需求', '完成可访问性检查']):
        assert (await client.post(path + '/updates', json={'expectedRevision': index + 1, 'text': text}, headers=key())).status_code == 201
    assert len((await client.get('/api/v1/work-items?q=客户确认需求')).json()['items']) == 1
    assert len((await client.get('/api/v1/work-items?q=未来计划')).json()['items']) == 1
    async with sessions() as db:
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='daily', period=now().date().isoformat(), period_end=now().date().isoformat(), timezone='UTC')
        rows = await report_inputs(db, report)
        facts = [report_source_content(row)['summary'] for row in rows]
        assert facts == ['客户确认需求', '完成可访问性检查']
        assert '未来计划' not in str(facts)


@pytest.mark.parametrize('blocks', [None, 'invalid', [None], [{'type': 'paragraph', 'attrs': None}]])
async def test_invalid_body_edits_never_500_or_mutate(setup, blocks):
    *_, clients = setup
    work = await create(clients['employee'])
    path = '/api/v1/work-items/' + work['id']
    response = await clients['employee'].patch(path, json={'expectedRevision': 1, 'bodyEdits': [{'action': 'replace', 'blockId': 'first', 'blocks': blocks}]}, headers=key())
    assert response.status_code == 422, response.text
    assert (await clients['employee'].get(path)).json()['body'] == work['body']


async def test_migration_keeps_old_dates_and_snapshots_without_new_progress(setup):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from datetime import timedelta
    from app.modules.work.models import WorkRevision
    _, sessions, _, clients = setup
    work = await create(clients['employee'])
    stamp = now() - timedelta(days=90)
    async with sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        row.content = {'title': row.title, 'summary': '旧记录\n第二行', 'status': 'blocked', 'blocker': '等待', 'nextStep': '', 'dueDate': '2026-10-08'}
        row.created_at = row.updated_at = stamp
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == row.id))
        revision.content, revision.created_at = dict(row.content), stamp
        await db.flush()
        migration = import_module('app.migrations.versions.0025_work_records')
        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync.connection())):
                migration.downgrade()
                migration.upgrade()
        await db.run_sync(cycle)
    async with sessions() as db:
        row = await db.get(WorkItem, work['id'])
        updates = (await db.scalars(select(WorkUpdate).where(WorkUpdate.work_id == row.id))).all()
        assert row.content['bodyText'] == '旧记录\n第二行'
        assert row.content['status'] == 'blocked' and row.updated_at == stamp
        assert len(updates) == 1 and updates[0].created_at == stamp


async def test_reports_keep_mixed_legacy_and_new_progress_once(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    first = await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '新版确认需求'}, headers=key())
    assert first.status_code == 201, first.text
    second = await client.post(path + '/progress', json={'expectedRevision': 2, 'title': work['title'], 'summary': '旧入口完成校对'})
    assert second.status_code == 200, second.text
    async with sessions() as db:
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='daily', period=now().date().isoformat(), period_end=now().date().isoformat(), timezone='UTC')
        facts = [report_source_content(row)['summary'] for row in await report_inputs(db, report)]
        assert facts == ['新版确认需求', '旧入口完成校对']


async def test_reports_correct_only_selected_imported_entry_and_preserve_saved_facts(setup):
    from datetime import timedelta
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.modules.work.models import WorkRevision
    from app.modules.reports.sources import report_fact_basis, sources_for
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    stamp = now() - timedelta(days=90)
    async with sessions.begin() as db:
        row = await db.get(WorkItem, work['id'])
        content = {'title': row.title, 'summary': '首次旧进展', 'status': 'in_progress', 'dueDate': None, 'blocker': '', 'nextStep': ''}
        first = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == row.id))
        first.content, first.created_at = dict(content), stamp
        second_content = {**content, 'summary': '另一次旧进展'}
        second = WorkRevision(company_id=row.company_id, owner_id=row.owner_id, work_id=row.id, revision=2, content=second_content, source_ids=[], access=row.access, created_at=stamp + timedelta(seconds=1))
        db.add(second)
        row.content, row.revision = second_content, 2
        await db.flush()
        migration = import_module('app.migrations.versions.0025_work_records')
        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync.connection())):
                migration.downgrade()
                migration.upgrade()
        await db.run_sync(cycle)
    async with sessions.begin() as db:
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='daily', period=stamp.date().isoformat(), period_end=stamp.date().isoformat(), timezone='UTC', source_ids=[])
        originals = await report_inputs(db, report)
        assert [report_source_content(row)['summary'] for row in originals] == ['首次旧进展', '另一次旧进展']
        report.source_ids = [row.id for row in originals]
        db.add(report)
        await db.flush()
        report_id = report.id
        original_facts = await report_fact_basis(db, users['employee'], report)
    path = '/api/v1/work-items/' + work['id']
    items = (await client.get(path + '/updates')).json()['items']
    first = next(item for item in items if item['text'] == '首次旧进展')
    corrected = await client.patch(path + '/updates/' + first['id'], json={'expectedRevision': 2, 'expectedUpdateRevision': 1, 'text': '更正后的首次进展'}, headers=key())
    assert corrected.status_code == 200, corrected.text
    async with sessions() as db:
        report = await db.get(Report, report_id)
        latest = await report_inputs(db, report)
        assert [report_source_content(row)['summary'] for row in latest] == ['更正后的首次进展', '另一次旧进展']
        assert await report_fact_basis(db, users['employee'], report) == original_facts
        assert len(await sources_for(db, report, users['employee'], [row.id for row in latest])) == 2
        with pytest.raises(ValueError, match='报告来源已变化'):
            await sources_for(db, report, users['employee'], report.source_ids)
    deleted = await client.request('DELETE', path + '/updates/' + first['id'], json={'expectedRevision': 3, 'expectedUpdateRevision': 2}, headers=key())
    assert deleted.status_code == 200, deleted.text
    async with sessions() as db:
        report = await db.get(Report, report_id)
        assert [report_source_content(row)['summary'] for row in await report_inputs(db, report)] == ['另一次旧进展']
        assert await report_fact_basis(db, users['employee'], report) == original_facts


async def test_single_update_reads_current_and_history_without_cross_work_or_owner_leaks(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    work = await create(client)
    another = await create(client, title='另一个独立工作')
    path = '/api/v1/work-items/' + work['id']
    created = await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '初稿完成'}, headers=key())
    assert created.status_code == 201
    update = created.json()['update']
    target = path + '/updates/' + update['id']
    current = await client.get(target)
    assert current.status_code == 200 and current.json() == update
    for role in ('peer', 'outsider'):
        for suffix in ('', '?revision=2'):
            denied = await clients[role].get(target + suffix)
            assert denied.status_code == 404 and '初稿完成' not in denied.text
    assert (await clients['admin'].get(target)).json()['text'] == '初稿完成'
    assert (await client.get('/api/v1/work-items/' + another['id'] + '/updates/' + update['id'])).status_code == 404
    assert (await client.get(target + '?revision=1')).status_code == 404
    changed = await client.patch(target, json={'expectedRevision': 2, 'expectedUpdateRevision': 1, 'text': '复核通过'}, headers=key())
    assert changed.status_code == 200
    assert (await client.get(target)).json()['text'] == '复核通过'
    historical = await client.get(target + '?revision=2')
    assert historical.status_code == 200 and historical.json()['text'] == '初稿完成'
    assert historical.json()['revision'] == 1 and historical.json()['workRevision'] == 2
    removed = await client.request('DELETE', target, json={'expectedRevision': 3, 'expectedUpdateRevision': 2}, headers=key())
    assert removed.status_code == 200
    assert (await client.get(target)).status_code == 404
    assert (await client.get(target + '?revision=4')).status_code == 404
    assert (await client.get(target + '?revision=3')).json()['text'] == '复核通过'
    async with sessions() as db:
        persisted = await db.get(WorkUpdate, update['id'])
        assert persisted.deleted and persisted.revision == 3
