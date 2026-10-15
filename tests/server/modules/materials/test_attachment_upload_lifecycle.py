"""Draft upload policy and retirement use real HTTP/database/filesystem boundaries."""
import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.input_rules import ATTACHMENT_RULES
from app.db.base import now
from app.modules.attachments.models import Attachment
from app.tasks.models import Job
from app.tasks.maintenance.maintenance import maintenance
from _support.materials.documents import upload
from _support.http.management import conversation, message

pytestmark = pytest.mark.asyncio


async def test_text_candidates_upload_without_reading_and_download_safely(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    for name in ['main.py', 'script.js', 'Main.TSX', 'Dockerfile', '.env', 'unknown.custom', 'page.html', 'vector.svg']:
        item = await upload(client, name, b'<script> invalid code\nsecond line', 'application/octet-stream')
        assert item['kind'] == 'document' and item['extraction']['status'] == 'unsent'
        content = await client.get(item['url'])
        assert content.content.startswith(b'<script>')
        assert 'attachment' in content.headers['content-disposition']
        assert content.headers['content-security-policy'].startswith('sandbox')
    async with sessions() as db:
        assert not (await db.scalars(select(Job).where(Job.owner_id == users['employee'].id))).all()


async def test_shared_blocklist_rejects_mime_spoof_and_preserves_office(setup):
    _, _, _, clients = setup
    client = clients['employee']
    for category in ATTACHMENT_RULES['blocked'].values():
        for suffix in category:
            response = await client.post('/api/v1/uploads', files={'file': ('sample.' + suffix.upper(), b'body', 'image/png')})
            assert response.status_code == 415, (suffix, response.text)
    for name in ['archive.tar.gz', '.exe', 'program.EXE. ']:
        assert (await client.post('/api/v1/uploads', files={'file': (name, b'body', 'text/plain')})).status_code == 415
    from _support.materials.document_samples import samples
    for name, raw in samples().items():
        if name.endswith(('.docx', '.pptx')):
            item = await upload(client, name, raw, 'application/octet-stream')
            assert item['extraction']['status'] == 'unsent'


async def test_draft_delete_is_owned_idempotent_and_durable_on_disk_failure(setup, monkeypatch):
    settings, sessions, _, clients = setup
    item = await upload(clients['employee'], 'source.py', b'print(1)', 'text/plain')
    url = '/api/v1/uploads/' + item['id']
    for role in ['peer', 'outsider', 'admin']:
        assert (await clients[role].delete(url)).status_code == 404
    import app.integrations.media as media
    original = media.remove_media
    def fail(*args):
        raise PermissionError('injected cleanup failure')
    monkeypatch.setattr(media, 'remove_media', fail)
    removed = await clients['employee'].delete(url)
    assert removed.status_code == 200 and removed.json()['cleanupPending']
    async with sessions() as db:
        row = await db.get(Attachment, item['id'])
        assert row.deleted and row.extraction_info['cleanup_pending']
    assert (settings.media_dir / item['id']).exists()
    assert (await clients['employee'].get(item['url'])).status_code == 404
    monkeypatch.setattr(media, 'remove_media', original)
    await maintenance(sessions, settings)
    assert not (settings.media_dir / item['id']).exists()
    assert (await clients['employee'].delete(url)).status_code == 200


async def test_sent_attachment_cannot_be_retired_and_expired_upload_is_unavailable(setup):
    settings, sessions, _, clients = setup
    client = clients['employee']
    item = await upload(client, 'a.py', b'print(1)', 'text/plain')
    conv = await conversation(client, 'attachments')
    await message(client, conv, '分析', [item['id']])
    assert (await client.delete('/api/v1/uploads/' + item['id'])).status_code == 409
    assert (settings.media_dir / item['id']).exists()
    expired = await upload(client, 'expired.py', b'print(2)', 'text/plain')
    async with sessions.begin() as db:
        (await db.get(Attachment, expired['id'])).created_at = now() - timedelta(hours=25)
    await maintenance(sessions, settings)
    assert (await client.get(expired['url'])).status_code == 404
    from _support.http.company import keyed
    expired_conversation = await conversation(client, 'expired attachment')
    headers = keyed()
    body = {'conversationId': expired_conversation['id'], 'text': '分析', 'attachmentIds': [expired['id']]}
    failed = await client.post('/api/v1/messages', headers=headers, json=body)
    assert failed.status_code == 404
    assert failed.json()['error']['code'] == 'attachment_unavailable'
    assert failed.json()['error']['message'] == '附件已不可用，请移除后重新添加。'
    # A rejected send does not reserve the key; a replacement can be accepted
    # and its repeated receipt still comes before attachment reuse validation.
    replacement = await upload(client, 'replacement.py', b'print(3)', 'text/plain')
    body['attachmentIds'] = [replacement['id']]
    accepted = await client.post('/api/v1/messages', headers=headers, json=body)
    repeated = await client.post('/api/v1/messages', headers=headers, json=body)
    assert accepted.status_code == repeated.status_code == 202
    assert accepted.json() == repeated.json()


async def test_unavailable_attachment_guidance_does_not_disclose_other_owners_or_conversations(setup):
    from app.db.base import uid
    from _support.http.company import keyed
    _, _, _, clients = setup
    item = await upload(clients['employee'], 'private.py', b'private', 'text/plain')
    assert (await clients['employee'].delete('/api/v1/uploads/' + item['id'])).status_code == 200
    for role in ('peer', 'outsider', 'admin'):
        client = clients[role]
        conv = await conversation(client)
        errors = []
        for identifier in (item['id'], uid()):
            response = await client.post('/api/v1/messages', headers=keyed(), json={
                'conversationId': conv['id'], 'text': 'read', 'attachmentIds': [identifier],
            })
            assert response.status_code == 404
            error = response.json()['error']
            errors.append((error['code'], error['message']))
        assert errors == [('not_found', '记录不存在或无权查看')] * 2
    # A missing conversation must not be presented as an expired attachment.
    response = await clients['employee'].post('/api/v1/messages', headers=keyed(), json={
        'conversationId': uid(), 'text': 'read', 'attachmentIds': [item['id']],
    })
    assert response.status_code == 404 and response.json()['error']['code'] == 'not_found'
    assert '重新添加' not in response.json()['error']['message']


async def test_maintenance_rechecks_sources_bound_after_candidate_snapshot_and_retires_orphans(setup, monkeypatch):
    import app.modules.attachments.lifecycle as lifecycle
    from app.modules.work.materials.service import bind_materials
    from app.modules.work.models import WorkItem, WorkMaterial
    from app.security.locks import company_lock
    from _support.work.work_records import create
    settings, sessions, users, clients = setup
    actor = users['employee']
    source = await upload(clients['employee'], 'source.py', b'print("retained")', 'text/plain')
    orphan = await upload(clients['employee'], 'orphan.py', b'print("orphan")', 'text/plain')
    work = await create(clients['employee'])
    async with sessions.begin() as db:
        for identifier in (source['id'], orphan['id']):
            (await db.get(Attachment, identifier)).created_at = now() - timedelta(hours=25)
    waiting = asyncio.Event()

    async def observed_company_lock(db, company_id):
        if company_id == actor.company_id:
            waiting.set()
        await company_lock(db, company_id)

    monkeypatch.setattr(lifecycle, 'company_lock', observed_company_lock)
    task = None
    try:
        async with sessions.begin() as binder:
            await company_lock(binder, actor.company_id)
            task = asyncio.create_task(maintenance(sessions, settings))
            # Maintenance has read its candidates, but cannot acquire the company
            # lock until the actual binding operation below commits.
            await asyncio.wait_for(waiting.wait(), 5)
            record = await binder.get(WorkItem, work['id'])
            await bind_materials(binder, actor, record, [{'attachmentId': source['id']}], settings)
        await asyncio.wait_for(task, 5)
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with sessions() as db:
        original = await db.get(Attachment, source['id'])
        material = await db.scalar(select(WorkMaterial).where(WorkMaterial.work_id == work['id']))
        assert material.source['attachmentId'] == source['id'] and not original.deleted
        assert (settings.media_dir / source['id']).read_bytes() == b'print("retained")'
        assert (settings.media_dir / material.attachment_id).read_bytes() == b'print("retained")'
        retired = await db.get(Attachment, orphan['id'])
        assert retired.deleted and not retired.extraction_info['cleanup_pending']
        assert not (settings.media_dir / orphan['id']).exists()


@pytest.mark.parametrize('first', ['delete', 'message', 'work', 'delete_work'])
async def test_binding_and_delete_serialize_without_destroying_formal_files(setup, first):
    from app.modules.attachments.lifecycle import retire_upload
    from app.modules.messages.commands import submit_message
    from app.modules.messages.schemas import SendMessage
    from app.modules.work.materials.service import bind_materials
    from app.modules.work.models import WorkItem, WorkMaterial
    from _support.work.work_records import create
    from _support.http.company import keyed
    settings, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    item = await upload(client, 'race.py', b'print("race")', 'text/plain')
    conv = await conversation(client)
    work = await create(client)
    before = set(settings.media_dir.iterdir())
    async with sessions() as db:
        async with db.begin():
            if first in ('delete', 'delete_work'):
                await retire_upload(db, actor, item['id'])
                if first == 'delete_work':
                    pending = asyncio.create_task(client.patch('/api/v1/work-items/' + work['id'], headers=keyed(), json={'expectedRevision': 1, 'materials': [{'attachmentId': item['id']}]}))
                else:
                    pending = asyncio.create_task(client.post('/api/v1/messages', headers=keyed(), json={'conversationId': conv['id'], 'text': 'read', 'attachmentIds': [item['id']]}))
            elif first == 'message':
                await submit_message(db, actor, SendMessage(conversationId=conv['id'], text='read', attachmentIds=[item['id']]), 'race-message', settings)
                pending = asyncio.create_task(client.delete('/api/v1/uploads/' + item['id']))
            else:
                record = await db.get(WorkItem, work['id'])
                await bind_materials(db, actor, record, [{'attachmentId': item['id']}], settings)
                pending = asyncio.create_task(client.delete('/api/v1/uploads/' + item['id']))
            await asyncio.sleep(0.02)
            assert not pending.done()
        response = await asyncio.wait_for(pending, 5)
    assert response.status_code == (404 if first.startswith('delete') else 409), response.text
    if first == 'delete_work':
        assert set(settings.media_dir.iterdir()) == before
        async with sessions() as db:
            assert not await db.scalar(select(WorkMaterial.id).where(WorkMaterial.work_id == work['id']))
            assert (await db.get(WorkItem, work['id'])).revision == 1
    if not first.startswith('delete'):
        assert (settings.media_dir / item['id']).read_bytes() == b'print("race")'


async def test_new_text_mixed_message_matches_text_baseline_and_reuses_parsing(setup, monkeypatch):
    import app.tasks.processing.documents as documents
    from _support.materials.document_fakes import DocumentModel
    from _support.materials.documents import run
    from pydantic import Field

    class CountedDocumentModel(DocumentModel):
        calls: int = 0
        tool_requests: list = Field(default_factory=list, exclude=True)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            result = await super()._agenerate(messages, stop, run_manager, **kwargs)
            self.tool_requests.extend(call['name'] for call in result.generations[0].message.tool_calls)
            return result

    settings, sessions, users, clients = setup
    client = clients['employee']
    parsed = []
    original = documents.parse_process

    async def counted_parse(*args, **kwargs):
        parsed.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(documents, 'parse_process', counted_parse)
    measurements = []
    for extension in ('txt', 'py'):
        conv = await conversation(client)
        source = await upload(client, 'source.' + extension, b'# SPEC070_MARKER\nthis is intentionally invalid source code', 'text/plain')
        binary = await upload(client, 'binary.unknown', b'\0\x01\x02\x03' * 20, 'application/octet-stream')
        assert source['extraction']['status'] == binary['extraction']['status'] == 'unsent'
        before = len(parsed)
        model = CountedDocumentModel(model='controlled-documents', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, query='SPEC070_MARKER')
        sent = await message(client, conv, '读取标记，不能把读取失败的文件当作已读。', [source['id'], binary['id']])
        await run(settings, sessions, users, sent, model)
        data = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
        states = {item['id']: item['extraction'] for item in data['attachments']}
        assert states[source['id']]['status'] == 'ready'
        assert states[binary['id']]['status'] == 'failed'
        assert '文本' in states[binary['id']]['error'] or '二进制' in states[binary['id']]['error']
        assert data['job']['state'] == 'awaiting_input', data
        assert 'SPEC070_MARKER' in data['reply']
        assert len(data['citations']) == 1 and data['citations'][0]['attachmentId'] == source['id']
        assert len(parsed) - before == 2
        measurements.append((model.calls, model.tool_requests, model.seen[0]['items'][0]['text']))
        revision = states[source['id']]['revision']
        before = len(parsed)
        followup = await message(client, conv, '再次读取同一个标记')
        await run(settings, sessions, users, followup, CountedDocumentModel(model='controlled-documents', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, query='SPEC070_MARKER'))
        assert len(parsed) == before
        extracted = (await client.get('/api/v1/uploads/' + source['id'] + '/extraction')).json()
        assert extracted['attachment']['extraction']['revision'] == revision
    assert measurements[0] == measurements[1]
    assert measurements[0][:2] == (3, ['find_documents', 'find_documents'])
