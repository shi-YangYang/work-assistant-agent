"""Saved files are work snapshots with the same authorization and transaction."""
import base64
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app.modules.attachments.models import Attachment
from app.modules.work.models import WorkMaterial, WorkItem, WorkRevision
from app.modules.executions.files import prepare_inputs
from app.modules.messages.models import Message
from app.tasks.models import Job
from app.modules.work.materials.service import register_copy_rollback
from app.agent.tools.work_records import read_work_material
from test_work_records import create, key, body
from test_documents import upload, run
from test_management import conversation, message, remove
from test_execution_permissions import mode_runtime

pytestmark = pytest.mark.asyncio


async def test_saved_chat_file_survives_source_deletion_and_is_actually_readable(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    conv = await conversation(client)
    original = await upload(client, 'requirements.txt', b'REQUIRED: blue navigation and export.', 'text/plain')
    sent = await message(client, conv, 'save this', [original['id']])
    saved = await client.patch('/api/v1/work-items/' + work['id'], json={'expectedRevision': 1, 'materials': [{'attachmentId': original['id']}], 'body': {'schemaVersion': 1, 'content': [*work['body']['content'], {'type': 'material', 'attrs': {'materialId': original['id']}}]}}, headers=key())
    assert saved.status_code == 200, saved.text
    material_id = saved.json()['materialIds'][0]
    assert saved.json()['work']['body']['content'][-1]['attrs']['materialId'] == material_id
    material = (await client.get(f"/api/v1/work-items/{work['id']}/materials/{material_id}")).json()
    copy = material['attachment']
    assert copy['id'] != original['id']
    async with sessions() as db:
        parse_job = await db.scalar(select(Job).where(Job.target_id == copy['id'], Job.kind == 'document'))
    await run(settings, sessions, users, {'jobId': parse_job.id})
    conv = (await client.get('/api/v1/conversations/' + conv['id'])).json()
    assert (await remove(client, 'conversations', conv)).status_code == 200
    assert (await client.get(copy['url'])).content == b'REQUIRED: blue navigation and export.'
    assert (await client.get(original['url'])).status_code == 404
    for role, expected in [('peer', 404), ('outsider', 404), ('admin', 200)]:
        assert (await clients[role].get(copy['url'])).status_code == expected
    context, current = await mode_runtime(setup, 'full', 'read saved work')
    result = json.loads(await read_work_material.coroutine(work['id'], material_id, SimpleNamespace(context=context)))
    assert 'blue navigation' in result['items'][0]['text']
    async with sessions.begin() as db:
        job = await db.get(Job, current['jobId'])
        current_message = await db.get(Message, current['messageId'])
        files, sources = await prepare_inputs(db, users['employee'], job, current_message, settings, [{'attachment_id': copy['id']}])
        assert base64.b64decode(files[0]['data']) == b'REQUIRED: blue navigation and export.'
        assert sources[0]['id'] == copy['id']


async def test_failed_bind_rolls_back_file_and_record_and_keeps_other_materials(setup):
    settings, sessions, _, clients = setup
    client = clients['employee']
    work = await create(client)
    first = await upload(client, 'one.txt', b'one', 'text/plain')
    before = set(settings.media_dir.iterdir())
    response = await client.patch('/api/v1/work-items/' + work['id'], json={'expectedRevision': 1, 'materials': [{'attachmentId': first['id']}, {'attachmentId': 'missing'}]}, headers=key())
    assert response.status_code == 404
    assert set(settings.media_dir.iterdir()) == before
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkMaterial)) == 0
        assert (await db.get(WorkItem, work['id'])).revision == 1


async def test_nested_commit_then_outer_rollback_removes_only_transaction_copies(setup):
    settings, sessions, *_ = setup
    first, second = settings.media_dir / 'outer-copy', settings.media_dir / 'nested-copy'
    settings.media_dir.mkdir(exist_ok=True)
    async with sessions() as db:
        async with db.begin():
            first.write_text('first')
            register_copy_rollback(db, first)
            try:
                async with db.begin_nested():
                    second.write_text('second')
                    register_copy_rollback(db, second)
                    raise ValueError('nested rejected')
            except ValueError:
                pass
            assert first.exists() and not second.exists()
            async with db.begin_nested():
                second.write_text('second')
                register_copy_rollback(db, second)
            await db.rollback()
    assert not first.exists() and not second.exists()


async def test_removed_material_current_denied_but_authorized_history_readable(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    attachment = await upload(client, 'record.txt', b'old file', 'text/plain')
    work = await create(client, materials=[{'attachmentId': attachment['id']}])
    path = '/api/v1/work-items/' + work['id']
    material = (await client.get(path + '/materials')).json()['items'][0]
    deleted = await client.request('DELETE', path + '/materials/' + material['id'], json={'expectedRevision': 1, 'expectedMaterialRevision': 1}, headers=key())
    assert deleted.status_code == 200, deleted.text
    assert (await client.get(material['attachment']['url'])).status_code == 404
    historical = (await client.get(path + '/materials?revision=1')).json()['items'][0]
    assert (await client.get(historical['attachment']['url'])).content == b'old file'
    assert (await clients['peer'].get(historical['attachment']['url'])).status_code == 404
    async with sessions() as db:
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id'], WorkRevision.revision == 2))
        assert revision.content['_changeKind'] == 'material_remove'


async def test_noop_does_not_rewrite_historical_change_metadata(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    async with sessions() as db:
        original = dict((await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))).content)
    assert (await client.patch(path, json={'expectedRevision': 1, 'title': work['title']}, headers=key())).json()['work']['revision'] == 1
    async with sessions() as db:
        assert (await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))).content == original


async def test_update_edit_preserves_unmentioned_materials_and_limits_combined_audio(setup):
    import hashlib
    settings, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    audios = []
    settings.media_dir.mkdir(exist_ok=True)
    async with sessions.begin() as db:
        for index in range(4):
            data = ('audio sample ' + str(index)).encode()
            row = Attachment(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='audio', name=f'{index}.wav', mime='audio/wav', size=len(data), sha256=hashlib.sha256(data).hexdigest(), duration=1)
            db.add(row)
            await db.flush()
            (settings.media_dir / row.id).write_bytes(data)
            audios.append(row.id)
    # Four files may exist across the work, but not in a single save/update.
    material_ids = []
    for index, identifier in enumerate(audios):
        response = await client.post(path + '/materials', json={'expectedRevision': index + 1, 'materials': [{'attachmentId': identifier}]}, headers=key())
        assert response.status_code == 201, response.text
        material_ids.extend(response.json()['materialIds'])
    for data in ({'materials': [{'attachmentId': i} for i in audios]}, {'materialIds': material_ids[:3], 'materials': [{'attachmentId': audios[3]}]}):
        response = await client.post(path + '/updates', json={'expectedRevision': 5, 'text': '录音进展', **data}, headers=key())
        assert response.status_code == 422, response.text
    result = (await client.post(path + '/updates', json={'expectedRevision': 5, 'text': '原记录', 'materialIds': material_ids[:2]}, headers=key())).json()
    changed = await client.patch(path + '/updates/' + result['update']['id'], json={'expectedRevision': 6, 'expectedUpdateRevision': 1, 'text': '更正记录'}, headers=key())
    assert changed.status_code == 200, changed.text
    assert changed.json()['update']['materialIds'] == material_ids[:2]


async def test_document_read_inherits_restricted_work_scope_into_saved_result(setup):
    from app.agent.tools.documents import read_document
    from app.agent.tools.deliverables import save_deliverable
    from app.modules.deliverables.models import Deliverable
    from app.modules.deliverables.queries import get_deliverable
    from app.modules.members.models import Member
    from app.security.access import scope
    from fastapi import HTTPException
    settings, sessions, users, clients = setup
    attachment = await upload(clients['admin'], 'team-notes.txt', b'controlled team notes', 'text/plain')
    work = await create(clients['admin'], materials=[{'attachmentId': attachment['id']}])
    material = (await clients['admin'].get('/api/v1/work-items/' + work['id'] + '/materials')).json()['items'][0]
    async with sessions.begin() as db:
        saved = await db.get(WorkItem, work['id'])
        saved.access = {**scope(users['admin']), 'team': True}
        parse = await db.scalar(select(Job).where(Job.kind == 'document', Job.target_id == material['attachment']['id']))
    await run(settings, sessions, users, {'jobId': parse.id})
    context, current = await mode_runtime(setup, 'full', '读取已保存工作资料并保存摘要', who='admin')
    runtime = SimpleNamespace(context=context)
    result = json.loads(await read_document.coroutine(material['attachment']['id'], 0, runtime))
    assert result['items'][0]['text'] == 'controlled team notes'
    output = json.loads(await save_deliverable.coroutine('资料摘要', 'controlled team notes', runtime))
    assert output['state'] == 'succeeded', output
    async with sessions.begin() as db:
        assert (await db.get(Job, current['jobId'])).access['team']
        item = await db.get(Deliverable, output['id'])
        assert item.access['team']
        actor = await db.get(Member, users['admin'].id)
        actor.role = 'employee'
        await db.flush()
        with pytest.raises(HTTPException):
            await get_deliverable(db, actor, item.id)


async def test_work_body_progress_and_material_pages_have_no_omissions_or_duplicates(setup):
    from app.agent.tools.work import get_work_item
    from app.agent.tools.work_records import list_work_materials, list_work_updates
    _, sessions, _, clients = setup
    client = clients['employee']
    document = {'schemaVersion': 1, 'content': [{'type': 'paragraph', 'attrs': {'id': f'block-{index}'}, 'content': [{'type': 'text', 'text': f'段落 {index}'}]} for index in range(23)]}
    work = await create(client, body=document)
    path = '/api/v1/work-items/' + work['id']
    all_material_ids, all_update_ids = [], []
    revision = 1
    for index in range(23):
        attachment = await upload(client, f'{index}.txt', f'material {index}'.encode(), 'text/plain')
        async with sessions.begin() as db:
            (await db.get(Attachment, attachment['id'])).extraction_status = 'ready'
        saved = await client.post(path + '/materials', json={'expectedRevision': revision, 'materials': [{'attachmentId': attachment['id']}]}, headers=key())
        assert saved.status_code == 201, saved.text
        revision = saved.json()['work']['revision']
        all_material_ids.extend(saved.json()['materialIds'])
        saved = await client.post(path + '/updates', json={'expectedRevision': revision, 'text': f'进展 {index}'}, headers=key())
        assert saved.status_code == 201, saved.text
        revision = saved.json()['work']['revision']
        all_update_ids.append(saved.json()['update']['id'])
    context, _ = await mode_runtime(setup, 'full', '分批读取全部工作内容和资料')
    runtime = SimpleNamespace(context=context)
    blocks, offset = [], 0
    while offset is not None:
        page = json.loads(await get_work_item.coroutine(work['id'], runtime, body_start=offset))
        blocks.extend(page['body']['content'])
        offset = page['nextBodyStart']
    assert blocks == work['body']['content']
    for resource, expected, tool in [('materials', all_material_ids, list_work_materials), ('updates', all_update_ids[::-1], list_work_updates)]:
        for agent in (False, True):
            identifiers, offset = [], 0
            while offset is not None:
                page = json.loads(await tool.coroutine(work['id'], runtime, start=offset)) if agent else (await client.get(path + '/' + resource, params={'start': offset})).json()
                identifiers.extend(item['id'] for item in page['items'])
                offset = page['nextCursor']
            assert identifiers == expected
            assert len(identifiers) == len(set(identifiers)) == 23
    assert [item['id'] for item in (await client.get('/api/v1/work-items', params={'q': '进展 0'})).json()['items']] == [work['id']]


@pytest.mark.parametrize('retainer', ['none', 'current_report', 'historical_report', 'candidate_report', 'deleted_member'])
async def test_saved_work_material_cleanup_respects_reports_and_account_deletion(setup, retainer):
    from app.modules.reports.models import Report, ReportRevision
    from app.modules.work.materials.cleanup import retire_orphans
    from app.modules.operations.mutations.deletion import clean_files
    settings, sessions, users, clients = setup
    client = clients['employee']
    attachment = await upload(client, 'retained.txt', b'retain only while referenced', 'text/plain')
    work = await create(client, materials=[{'attachmentId': attachment['id']}])
    other = await create(clients['peer'], materials=[{'attachmentId': (await upload(clients['peer'], 'other.txt', b'other live record', 'text/plain'))['id']}])
    material = (await client.get('/api/v1/work-items/' + work['id'] + '/materials')).json()['items'][0]
    other_material = (await clients['peer'].get('/api/v1/work-items/' + other['id'] + '/materials')).json()['items'][0]
    file_id = material['attachment']['id']
    async with sessions.begin() as db:
        source = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))
        report = None
        if retainer.endswith('_report'):
            report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='daily', period='2026-09-30', period_end='2026-09-30', timezone='UTC', content={'ongoing': '已保存资料'}, source_ids=[source.id] if retainer == 'current_report' else [], candidate={'content': {'ongoing': '候选报告'}, 'sourceIds': [source.id]} if retainer == 'candidate_report' else None)
            db.add(report)
            await db.flush()
            if retainer == 'historical_report':
                report.published_revision = 1
                db.add(ReportRevision(company_id=report.company_id, owner_id=report.owner_id, report_id=report.id, revision=1, content=report.content, source_ids=[source.id]))
    if retainer == 'deleted_member':
        response = await clients['admin'].delete('/api/v1/members/' + users['employee'].id)
    else:
        response = await client.request('DELETE', '/api/v1/work-items/' + work['id'], json={'expectedRevision': 1})
    assert response.status_code == 200, response.text
    async with sessions.begin() as db:
        await retire_orphans(db)
        await clean_files(db, settings)
        assert (await db.get(Attachment, file_id)).deleted == (report is None)
    assert (settings.media_dir / file_id).exists() == (report is not None)
    assert (await clients['admin'].get(material['attachment']['url'])).status_code == 404
    assert (await clients['peer'].get(other_material['attachment']['url'])).content == b'other live record'
    if report:
        response = await clients['admin'].request('DELETE', '/api/v1/reports/' + report.id, json={'expectedRevision': 1})
        assert response.status_code == 200, response.text
        async with sessions.begin() as db:
            await retire_orphans(db)
            await clean_files(db, settings)
            assert (await db.get(Attachment, file_id)).deleted
        assert not (settings.media_dir / file_id).exists()


async def test_submitted_report_keeps_progress_snapshot_and_file_after_correction(setup):
    from copy import deepcopy
    from app.db.base import now
    from app.modules.reports.models import Report, ReportRevision
    from app.modules.reports.sources import report_inputs, report_fact_basis
    from app.modules.operations.mutations.deletion import clean_files
    settings, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    path = '/api/v1/work-items/' + work['id']
    attachment = await upload(client, 'confirmed.txt', b'original confirmation evidence', 'text/plain')
    saved = await client.post(path + '/updates', json={'expectedRevision': 1, 'text': '客户确认初稿', 'materials': [{'attachmentId': attachment['id']}]}, headers=key())
    assert saved.status_code == 201, saved.text
    update = saved.json()['update']
    material_id = update['materialIds'][0]
    historical = (await client.get(path + '/materials?revision=2')).json()['items'][0]
    file_id = historical['attachment']['id']
    async with sessions.begin() as db:
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='daily', period=now().date().isoformat(), period_end=now().date().isoformat(), timezone='UTC', content={'completed': '', 'ongoing': '客户确认初稿', 'blockers': '', 'next': ''})
        sources = await report_inputs(db, report)
        assert len(sources) == 1
        report.source_ids = [sources[0].id]
        original_source = deepcopy(sources[0].content)
        db.add(report)
        await db.flush()
        report_id, source_ids = report.id, list(report.source_ids)
    submitted = await client.post('/api/v1/reports/' + report_id + '/submit', json={'expectedRevision': 1}, headers=key())
    assert submitted.status_code == 200, submitted.text
    async with sessions() as db:
        published = await db.scalar(select(ReportRevision).where(ReportRevision.report_id == report_id))
        original_report = deepcopy(published.content)
        original_facts = await report_fact_basis(db, users['employee'], published)
        assert original_facts['items'][0]['content']['summary'] == '客户确认初稿'
    corrected = await client.patch(path + '/updates/' + update['id'], json={'expectedRevision': 2, 'expectedUpdateRevision': 1, 'text': '更正：客户尚待确认', 'materialIds': []}, headers=key())
    assert corrected.status_code == 200, corrected.text
    removed = await client.request('DELETE', path + '/materials/' + material_id, json={'expectedRevision': 3, 'expectedMaterialRevision': 1}, headers=key())
    assert removed.status_code == 200, removed.text
    async with sessions.begin() as db:
        await clean_files(db, settings)
        published = await db.scalar(select(ReportRevision).where(ReportRevision.report_id == report_id))
        assert published.revision == 1 and published.content == original_report
        assert published.source_ids == source_ids
        assert (await db.get(WorkRevision, source_ids[0])).content == original_source
        assert await report_fact_basis(db, users['employee'], published) == original_facts
        assert not (await db.get(Attachment, file_id)).deleted
    report = (await client.get('/api/v1/reports/' + report_id, params={'revision': 1})).json()
    assert report['content'] == original_report and report['sourceIds'] == source_ids
    entries = (await client.get(path + '/updates', params={'revision': 2})).json()['items']
    assert entries[0]['text'] == '客户确认初稿' and entries[0]['materialIds'] == [material_id]
    assert (await client.get(path + '/updates')).json()['items'][0]['text'] == '更正：客户尚待确认'
    assert (await client.get(historical['attachment']['url'])).content == b'original confirmation evidence'
    assert (settings.media_dir / file_id).read_bytes() == b'original confirmation evidence'
