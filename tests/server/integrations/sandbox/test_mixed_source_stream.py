"""Mixed attachments from several messages retain provenance without becoming documents."""
import hashlib

import pytest
from fastapi import HTTPException

from app.db.base import uid
from app.modules.attachments.models import Attachment
from app.tasks.models import Job
from app.tasks.streaming.publisher import ReplyPublisher
from _support.agent.builtin_execution import read
from _support.agent.business_actions import finish, runtime
from _support.agent.execution_evidence import followup
from _support.agent.sandbox_execution import receipts, run
from _support.materials.deliverables import read_plan

pytestmark = pytest.mark.asyncio


async def mixed_batches(setup):
    settings, sessions, users, _ = setup
    context, sent = await runtime(setup, '根据分批提交的附件生成文件')
    documents, images, audio = {}, {}, []
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    # Seed already uploaded attachments: three messages, eight files each.
    # Extraction and provider execution are outside this provenance regression.
    for batch in range(3):
        if batch:
            await finish(context)
            context = await followup(setup, sent['conversationId'])
        async with sessions.begin() as db:
            message_id = (await db.get(Job, context.job_id)).target_id
            for index, kind in enumerate(['document'] * 6 + ['image', 'audio']):
                identifier = uid()
                data = f'controlled source {batch}/{index}'.encode()
                (settings.media_dir / identifier).write_bytes(data)
                revision = 1 if kind == 'document' else 0
                extension, mime = {'document': ('csv', 'text/csv'), 'image': ('png', 'image/png'),
                                   'audio': ('wav', 'audio/wav')}[kind]
                db.add(Attachment(id=identifier, company_id=users['employee'].company_id,
                                  owner_id=users['employee'].id, message_id=message_id, kind=kind,
                                  mime=mime, name=f'input-{batch}-{index}.{extension}', size=len(data),
                                  sha256=hashlib.sha256(data).hexdigest(), extraction_revision=revision))
                if kind == 'document':
                    documents[identifier] = revision
                elif kind == 'image':
                    images[identifier] = message_id
                else:
                    audio.append(identifier)
    context.document_versions.update(documents)
    context.image_sources.update(images)
    return context, sent['conversationId'], documents, images, audio


@pytest.mark.parametrize('entry', ['generated', 'execution-history', 'deliverable-history'])
@pytest.mark.parametrize('revoked_kind', ['image', 'audio'])
async def test_mixed_batch_sources_stream_and_remain_revocable(setup, receipts, entry, revoked_kind):
    _, sessions, _, clients = setup
    context, conversation_id, documents, images, audio = await mixed_batches(setup)
    result = await run(context, input_refs=[{'attachment_id': identifier} for identifier in [*images, *audio]])
    assert result['state'] == 'succeeded', result
    delivery = result['delivery']
    if entry != 'generated':
        await finish(context)
        context = await followup(setup, conversation_id)
        if entry == 'execution-history':
            restored = await read(context, result['executionId'])
            assert restored['historical'] and restored['deliveryState'] == 'available'
        else:
            restored = await read_plan(context, delivery['id'])
            assert restored['files'] == delivery['files']
    publisher = ReplyPublisher(context, 'mixed-attachment-result')
    try:
        await publisher.start()
        await publisher.write('已根据分批附件生成文件。')
        await publisher.drain()
        snapshot = await publisher.store.snapshot(publisher.identity)
        assert snapshot['text'] == '已根据分批附件生成文件。'
        assert snapshot['source']['documents'] == documents
        assert context.document_versions == documents
        async with sessions() as db:
            job = await db.get(Job, context.job_id)
            assert {ref['id'] for ref in job.result['sandboxSources']} == set(documents) | set(images) | set(audio)
        url = delivery['files'][0]['url']
        assert (await clients['employee'].get(url)).status_code == 200
        # Filtering the document-only map must not discard image/audio permissions.
        identifier = next(iter(images)) if revoked_kind == 'image' else audio[0]
        async with sessions.begin() as db:
            attachment = await db.get(Attachment, identifier)
            attachment.deleted = True
        assert (await clients['employee'].get(url)).status_code == 403
        await publisher.write('不应继续发布。')
        with pytest.raises(HTTPException):
            await publisher.drain()
        assert not (await publisher.store.snapshot(publisher.identity)).get('text')
        assert receipts.count == 1
    finally:
        await publisher.close()
