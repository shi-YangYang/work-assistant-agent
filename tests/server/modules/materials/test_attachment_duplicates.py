"""Repeated uploads keep independent identity; processing reuse is message-local."""
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from app.agent.tools.resources.documents import read_document
from app.modules.attachments.duplicates import unique_names
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.messages.input.audio import transcript_groups
from app.tasks.models import Job
from app.tasks.processing import documents, handlers
from _support.agent.fakes import controlled_model
from _support.http.management import conversation, message
from _support.materials.document_fakes import DocumentModel
from _support.materials.documents import run, running_context, upload

pytestmark = pytest.mark.asyncio


class CountedModel(DocumentModel):
    calls: int = 0
    requests: list = Field(default_factory=list, exclude=True)

    async def _agenerate(self, messages, **kwargs):
        self.calls += 1
        result = await super()._agenerate(messages, **kwargs)
        self.requests.extend(call['name'] for call in result.generations[0].message.tool_calls)
        return result


async def test_repeated_uploads_parse_once_keep_names_references_and_model_call_count(setup, monkeypatch):
    settings, sessions, users, clients = setup
    client = clients['employee']
    parse, prepare = documents.parse_process, handlers.prepare_document
    calls, measurements = [], []

    async def counted(*args):
        calls.append(args)
        return await parse(*args)

    async def without_reuse(context, identifier, **kwargs):
        return await prepare(context, identifier)

    monkeypatch.setattr(documents, 'parse_process', counted)
    for reuse in (False, True):
        monkeypatch.setattr(handlers, 'prepare_document', prepare if reuse else without_reuse)
        conv = await conversation(client)
        uploads = [await upload(client, '发票.txt', b'UNIQUE_MARKER: one invoice, amount 100') for _ in range(3)]
        assert len({item['id'] for item in uploads}) == 3
        assert all(item['extraction']['status'] == 'unsent' for item in uploads)
        before = len(calls)
        sent = await message(client, conv, '读取材料并说明重复情况', [item['id'] for item in uploads])
        model = CountedModel(model='controlled-documents', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, query='UNIQUE_MARKER')
        start = time.monotonic()
        await run(settings, sessions, users, sent, model)
        elapsed = time.monotonic() - start
        data = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
        assert data['job']['state'] == 'awaiting_input', data
        assert {item['name'] for item in data['attachments']} == {'发票.txt', '发票 (2).txt', '发票 (3).txt'}
        assert len(data['citations']) == 1
        assert len(model.seen[0]['sameContentAttachments']) == 2
        assert '材料范围' not in data['reply']
        async with sessions() as db:
            scope = (await db.get(Job, sent['jobId'])).result['materialCoverage']
            assert '复用自相同内容附件' in '\n'.join(scope)
        for item in data['attachments']:
            assert (await client.get(item['url'])).content == b'UNIQUE_MARKER: one invoice, amount 100'
            extraction = (await client.get('/api/v1/uploads/' + item['id'] + '/extraction')).json()
            assert extraction['items'][0]['text'] == model.seen[0]['items'][0]['text']
        assert len(calls) - before == (1 if reuse else 3)
        measurements.append({'reuse': reuse, 'seconds': round(elapsed, 3), 'parses': len(calls) - before, 'modelCalls': model.calls, 'tools': model.requests})
    assert measurements[0]['modelCalls'] == measurements[1]['modelCalls']
    assert measurements[0]['tools'] == measurements[1]['tools']
    print('duplicate_processing_comparison=' + json.dumps(measurements))


async def test_names_reserve_numbered_inputs_and_preserve_long_extensions():
    assert unique_names(['a.txt', 'a.txt', 'a (2).txt', 'a.txt']) == ['a.txt', 'a (3).txt', 'a (2).txt', 'a (4).txt']
    for name in ('长' * 176 + '.txt', 'README', '.env'):
        names = unique_names([name] * 3)
        assert len(set(names)) == 3 and all(len(item) <= 180 for item in names)
        if name.endswith('.txt'):
            assert all(item.endswith('.txt') for item in names)


async def test_distinct_content_and_formats_do_not_share_parse_or_failed_results(setup, monkeypatch):
    settings, sessions, users, clients = setup
    client = clients['employee']
    inputs = [('same.txt', b'first'), ('same.txt', b'second'), ('raw.txt', b'not json'),
              ('raw.json', b'not json'), ('broken.json', b'not json')]
    uploads = [await upload(client, name, data) for name, data in inputs]
    conv = await conversation(client)
    sent = await message(client, conv, '处理材料', [item['id'] for item in uploads])
    parse = documents.parse_process
    calls = []
    async def counted(*args):
        calls.append(args)
        return await parse(*args)
    monkeypatch.setattr(documents, 'parse_process', counted)
    await run(settings, sessions, users, sent)
    assert len(calls) == 5
    async with sessions() as db:
        rows = {item.id: item for item in (await db.scalars(select(Attachment).where(Attachment.message_id == sent['messageId']))).all()}
        assert [rows[item['id']].extraction_status for item in uploads] == ['ready', 'ready', 'ready', 'failed', 'failed']
        chunks = [(await db.scalars(select(DocumentChunk.text).where(DocumentChunk.attachment_id == item['id']))).all() for item in uploads[:2]]
        assert chunks == [['first'], ['second']]


async def test_cache_cannot_cross_messages_owners_or_hide_corrupt_copy(setup, monkeypatch):
    settings, sessions, users, clients = setup
    parse, calls, cache = documents.parse_process, [], {}
    async def counted(*args):
        calls.append(args)
        return await parse(*args)
    monkeypatch.setattr(documents, 'parse_process', counted)
    first = await upload(clients['employee'], 'same.txt', b'original')
    copy = await upload(clients['employee'], 'same.txt', b'original')
    sent = await message(clients['employee'], await conversation(clients['employee']), '', [first['id'], copy['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    await documents.prepare_document(context, first['id'], parse_cache=cache)
    (settings.media_dir / copy['id']).write_bytes(b'corrupt')
    failed = await documents.prepare_document(context, copy['id'], parse_cache=cache)
    assert failed['extraction']['status'] == 'failed' and len(calls) == 1
    for role in ('employee', 'peer'):
        other = await upload(clients[role], 'same.txt', b'original')
        next_sent = await message(clients[role], await conversation(clients[role]), '', [other['id']])
        with pytest.raises(HTTPException):
            await documents.prepare_document(context, other['id'], parse_cache=cache)
        async with sessions.begin() as db:
            previous_job = await db.get(Job, context.job_id)
            previous_job.state, previous_job.lease_until = 'succeeded', None
        next_context = await running_context(settings, sessions, users[role], next_sent)
        await documents.prepare_document(next_context, other['id'], parse_cache=cache)
        context = next_context
    assert len(calls) == 3


async def test_reused_read_coverage_is_only_returned_chunks_and_excludes_changed_revision(setup):
    settings, sessions, users, clients = setup
    client, cache = clients['employee'], {}
    # Many short lines produce multiple pages under the real parser's limits.
    raw = ('sample line ' + 'x' * 150 + '\n') * 1000
    files = [await upload(client, 'long.txt', raw.encode()) for _ in range(2)]
    sent = await message(client, await conversation(client), '', [item['id'] for item in files])
    context = await running_context(settings, sessions, users['employee'], sent)
    prepared = [await documents.prepare_document(context, item['id'], parse_cache=cache) for item in files]
    versions = {item['id']: item['extraction']['revision'] for item in prepared}
    context.document_equivalents = {identifier: versions for identifier in versions}
    result = json.loads(await read_document.coroutine(attachment_id=files[0]['id'], start=0, runtime=SimpleNamespace(context=context)))
    assert result['nextCursor'] is not None
    assert {entry[2] for entry in context.document_reads.values() if entry[0] == files[1]['id']} == {row['ordinal'] for row in result['items']}
    async with sessions.begin() as db:
        changed = await db.get(Attachment, files[1]['id'])
        changed.extraction_revision += 1
    context.document_reads.clear()
    result = json.loads(await read_document.coroutine(attachment_id=files[0]['id'], start=0, runtime=SimpleNamespace(context=context)))
    assert 'sameContentAttachments' not in result
    assert all(entry[0] == files[0]['id'] for entry in context.document_reads.values())


async def test_identical_images_and_audio_keep_all_sources_with_one_processing_per_content(setup, monkeypatch):
    import io
    import wave
    from PIL import Image
    settings, sessions, users, clients = setup
    client = clients['employee']
    image = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(image, 'PNG')
    recording = io.BytesIO()
    with wave.open(recording, 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
        stream.writeframes(b'\0\0' * 1600)
    images = [await upload(client, 'image.png', image.getvalue(), 'image/png') for _ in range(2)]
    audios = [await upload(client, 'voice.wav', recording.getvalue(), 'audio/wav') for _ in range(2)]
    calls, blocks = [], []
    async def recognize(context, attachment):
        calls.append(attachment.id)
        return '相同的录音文字'
    invoke = handlers.invoke_harness
    async def inspect(context, saver, content, model):
        blocks.extend(content)
        return await invoke(context, saver, content, model)
    monkeypatch.setattr('app.tasks.processing.asr.asr', recognize)
    monkeypatch.setattr(handlers, 'invoke_harness', inspect)
    sent = await message(client, await conversation(client), '查看材料', [item['id'] for item in [*images, *audios]], voiceCommandAttachmentIds=[audios[0]['id']])
    await run(settings, sessions, users, sent, controlled_model('clarify'))
    data = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert data['job']['state'] == 'awaiting_input', data
    assert len(data['attachments']) == 4 and len(calls) == 1
    assert sum(block['type'] == 'image_url' for block in blocks) == 1
    manifest = json.loads(blocks[0]['text'].split('本次完整附件清单：')[1].split('\n')[0])
    inventory = manifest['attachments']
    assert manifest['attachmentSummary']['total'] == 4
    assert manifest['attachmentSummary']['countsByKind'] == {'image': 2, 'audio': 2}
    assert len(inventory) == 4 and sum('sameContentAs' in item for item in inventory) == 2
    async with sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert set(job.result['audioTranscripts']) == {item['id'] for item in audios}
        instructions, material = transcript_groups(data['transcript'], job.result)
        assert 'voice.wav' in instructions and 'voice (2).wav' in material
