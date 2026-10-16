"""Real upload/worker/conversion/read flows; only the external LLM is controlled."""
import base64
import io
import json
import wave
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from PIL import Image
from pydantic import Field
from sqlalchemy import select

from _support.agent.execution_permissions import mode_runtime
from _support.agent.fakes import ReviewedFixtureModel, completion
from _support.http.company import keyed
from _support.http.management import conversation, message, remove
from _support.materials.documents import run, upload
from _support.materials.legacy_samples import TEXT, legacy_samples
from _support.work.work_records import create
from app.agent.tools.business.work_records import read_work_material
from app.integrations.parsing.office_conversion import converter
from app.modules.attachments.models import DocumentChunk
from app.modules.executions.files import prepare_inputs
from app.modules.messages.models import Message
from app.tasks.models import Job
from app.tasks.processing import documents

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope='module')
def real_office():
    if not converter()[0]:
        pytest.skip('Real LibreOffice is required for legacy Office workflow tests')
    return legacy_samples()


class ReadAllModel(ReviewedFixtureModel):
    """Read directory and content pages through real tools, then persist a result."""
    pending: list = Field(default_factory=list, exclude=True)
    seen: list = Field(default_factory=list, exclude=True)
    directory: list = Field(default_factory=list, exclude=True)
    calls: list = Field(default_factory=list, exclude=True)
    create_result: bool = False
    saved: dict = Field(default_factory=dict, exclude=True)

    async def _agenerate(self, messages, **kwargs):
        last = messages[-1]
        def call(name, args):
            self.calls.append(name)
            return AIMessage(content='', tool_calls=[{'id': f'office-{len(self.calls)}', 'name': name, 'args': args}])
        reply = None
        if isinstance(last, ToolMessage) and last.name == 'find_documents':
            data = json.loads(last.content)
            self.directory.extend(data['items'])
            self.pending.extend(row['id'] for row in data['items'])
            if data['nextCursor'] is not None:
                reply = call('find_documents', {'query': '', 'start': data['nextCursor']})
        elif isinstance(last, ToolMessage) and last.name == 'read_document':
            data = json.loads(last.content)
            self.seen.append(data)
            if data.get('nextCursor') is not None:
                reply = call('read_document', {'attachment_id': data['attachment']['id'], 'start': data['nextCursor']})
        elif isinstance(last, ToolMessage) and last.name == 'save_deliverable':
            self.saved = json.loads(last.content)
            assert self.saved.get('state') == 'succeeded', self.saved
            reply = completion('已保存汇总。\n' + self.body())
        else:
            names = {tool['function']['name'] for tool in kwargs.get('tools', [])}
            reply = call('find_documents', {'query': ''}) if 'find_documents' in names else call('load_tools', {'groups': ['documents']})
        if reply is None:
            if self.pending:
                reply = call('read_document', {'attachment_id': self.pending.pop(0), 'start': 0})
            elif self.create_result:
                reply = call('save_deliverable', {'title': '跨批次材料汇总', 'body': self.body()})
            else:
                reply = completion(self.body())
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def body(self):
        text = []
        for data in self.seen:
            attachment = data['attachment']
            text.append('文件：' + attachment['name'])
            if attachment['extraction']['status'] == 'failed':
                text.append('未能读取：' + attachment['extraction']['error'])
            text.extend(row['location'] + '：' + row['text'] + row['citation'] for row in data['items'])
        return '\n'.join(text) or '没有可读取材料。'


def reader(**kwargs):
    return ReadAllModel(model='controlled-office', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, **kwargs)


async def refreshed(client, sent):
    response = await client.get('/api/v1/messages/' + sent['messageId'])
    assert response.status_code == 200, response.text
    return response.json()


def assert_answered(data, *, saved=False):
    # Read-only chat deliberately remains awaiting_input; saved deliverables succeed.
    assert data['job']['state'] == ('succeeded' if saved else 'awaiting_input'), data
    assert data['reply'] and not data['job']['error'], data


async def test_seven_formats_upload_without_reading_then_answer_refresh_and_followup(setup, real_office, monkeypatch):
    settings, sessions, users, clients = setup
    client = clients['employee']
    converted, parsed = [], []
    convert, parse = documents.parse_office, documents.parse_process
    async def count_convert(*args, **kwargs):
        converted.append(args[1])
        return await convert(*args, **kwargs)
    async def count_parse(*args, **kwargs):
        parsed.append(args[1])
        return await parse(*args, **kwargs)
    monkeypatch.setattr(documents, 'parse_office', count_convert)
    monkeypatch.setattr(documents, 'parse_process', count_parse)
    files = [await upload(client, name, data) for name, data in real_office.items()]
    ordinary = await upload(client, '代码.py', b'print("MODERN_CODE_MARKER")')
    raw = io.BytesIO(); Image.new('RGB', (2, 2), 'red').save(raw, 'PNG')
    picture = await upload(client, '材料图片.png', raw.getvalue(), 'image/png')
    all_files = [*files, ordinary, picture]
    model = reader()
    assert not converted and not parsed and not model.calls
    assert all(item['extraction']['status'] == 'unsent' for item in [*files, ordinary])
    async with sessions() as db:
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id.in_([f['id'] for f in files])))
        assert not await db.scalar(select(Job.id).where(Job.owner_id == users['employee'].id))
    conv = await conversation(client)
    sent = await message(client, conv, '逐一读取材料并给出原文依据', [item['id'] for item in all_files])
    await run(settings, sessions, users, sent, model)
    data = await refreshed(client, sent)
    assert_answered(data)
    assert [item['id'] for item in data['attachments']] == [item['id'] for item in all_files]
    assert len(converted) == 7 and parsed == ['.py']
    assert len(model.seen) == 8
    assert TEXT in data['reply'] and 'MODERN_CODE_MARKER' in data['reply']
    assert {item['attachmentId'] for item in data['citations']} == {item['id'] for item in [*files, ordinary]}
    for item in files:
        detail = (await client.get('/api/v1/uploads/' + item['id'] + '/extraction')).json()
        extraction = detail['attachment']['extraction']
        assert extraction['status'] in ('ready', 'partial'), extraction
        assert TEXT in '\n'.join(row['text'] for row in detail['items'])
        assert extraction['originalFormat'] == item['name'].rsplit('.', 1)[1]
        assert 'stage' not in extraction
        assert (await client.get(item['url'])).content == real_office[item['name']]
        for role in ('peer', 'admin', 'outsider'):
            assert (await clients[role].get(item['url'])).status_code == 404
            assert (await clients[role].get('/api/v1/uploads/' + item['id'] + '/extraction')).status_code == 404
    followup = await message(client, conv, '再次列出上批材料的原文与来源')
    followup_model = reader()
    await run(settings, sessions, users, followup, followup_model)
    after = await refreshed(client, followup)
    assert_answered(after)
    assert TEXT in after['reply']
    assert len(converted) == 7 and parsed == ['.py']
    assert {item['attachmentId'] for item in after['citations']} == {item['id'] for item in [*files, ordinary]}


async def test_duplicate_legacy_identity_bad_file_retry_and_other_account_recovery(setup, real_office, monkeypatch):
    settings, sessions, users, clients = setup
    client = clients['employee']
    calls, convert = [], documents.parse_office
    async def counted(*args, **kwargs):
        calls.append(args[1])
        return await convert(*args, **kwargs)
    monkeypatch.setattr(documents, 'parse_office', counted)
    # Equal extension/name does not establish content identity; .doc may contain RTF.
    inputs = [('相同.doc', real_office['sample.doc']), ('相同.doc', real_office['sample.doc']),
              ('相同.doc', b'{\\rtf1\\ansi DIFFERENT_CONTENT_071}'),
              ('损坏.doc', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\0' * 512)]
    files = [await upload(client, name, raw) for name, raw in inputs]
    sent = await message(client, await conversation(client), '读取全部可读文件，明确哪些失败', [f['id'] for f in files])
    model = reader()
    await run(settings, sessions, users, sent, model)
    data = await refreshed(client, sent)
    assert_answered(data)
    assert len(calls) == 3
    assert [f['name'] for f in data['attachments']] == ['相同.doc', '相同 (2).doc', '相同 (3).doc', '损坏.doc']
    assert TEXT in data['reply'] and 'DIFFERENT_CONTENT_071' in data['reply'] and '未能读取' in data['reply']
    assert [f['extraction']['status'] for f in data['attachments']] == ['ready', 'ready', 'ready', 'failed']
    assert files[-1]['id'] not in {c['attachmentId'] for c in data['citations']}
    before = [f['extraction']['revision'] for f in data['attachments'][:3]]
    retry = await client.post('/api/v1/uploads/' + files[-1]['id'] + '/retry', json={})
    assert retry.status_code == 202, retry.text
    await run(settings, sessions, users, {'jobId': retry.json()['id']})
    after = await refreshed(client, sent)
    assert len(calls) == 4 and len(model.calls) > 0
    assert [f['extraction']['revision'] for f in after['attachments'][:3]] == before
    assert after['attachments'][-1]['extraction']['status'] == 'failed'
    # A malformed file cannot poison this worker or another user's next request.
    for role in ('employee', 'peer'):
        good = await upload(clients[role], '恢复.doc', real_office['sample.doc'])
        next_sent = await message(clients[role], await conversation(clients[role]), '读取新文件', [good['id']])
        await run(settings, sessions, users, next_sent, reader())
        result = await refreshed(clients[role], next_sent)
        assert_answered(result)
        assert TEXT in result['reply']
        assert (await clients['outsider'].get(good['url'])).status_code == 404


async def test_batches_exceed_message_limit_read_early_files_and_save_real_result(setup, real_office):
    settings, sessions, users, clients = setup
    client = clients['employee']
    files = [await upload(client, '首批旧文件.doc', real_office['sample.doc'])]
    files.extend([await upload(client, f'批次-{index}.txt', f'BATCH_VALUE_{index:02d}'.encode()) for index in range(11)])
    conv = await conversation(client)
    rejected = await client.post('/api/v1/messages', json={'conversationId': conv['id'], 'text': '不可绕过上限', 'attachmentIds': [f['id'] for f in files[:10]]}, headers=keyed())
    assert rejected.status_code == 422, rejected.text
    for index, group in enumerate((files[:6], files[6:])):
        sent = await message(client, conv, '读取材料并保存跨批次汇总' if index else '读取第一批材料', [f['id'] for f in group])
        model = reader(create_result=bool(index))
        await run(settings, sessions, users, sent, model)
        data = await refreshed(client, sent)
        assert_answered(data, saved=bool(index))
    assert len(model.directory) == 12 and model.calls.count('find_documents') == 2
    assert len(model.seen) == 12
    expected = [TEXT, *(f'BATCH_VALUE_{index:02d}' for index in range(11))]
    assert all(value in data['reply'] for value in expected)
    assert {item['attachmentId'] for item in data['citations']} == {item['id'] for item in files}
    saved = (await client.get('/api/v1/deliverables/' + model.saved['id'])).json()
    assert all(value in saved['body'] for value in expected)
    assert saved['revision'] == 1
    assert (await clients['peer'].get('/api/v1/deliverables/' + saved['id'])).status_code == 404
    # Reload and a new turn still read original persisted chunks, including batch one.
    followup = await message(client, conv, '复核全部原始材料')
    await run(settings, sessions, users, followup, reader())
    after = await refreshed(client, followup)
    assert_answered(after)
    assert all(value in after['reply'] for value in expected)
    async with sessions() as db:
        persisted = (await db.scalars(select(DocumentChunk.attachment_id).where(DocumentChunk.attachment_id.in_([f['id'] for f in files])).distinct())).all()
        assert set(persisted) == {f['id'] for f in files}


async def test_saved_legacy_material_keeps_original_after_source_deletion(setup, real_office):
    settings, sessions, users, clients = setup
    client = clients['employee']
    original = await upload(client, '原始合同.doc', real_office['sample.doc'])
    conv = await conversation(client)
    sent = await message(client, conv, '保存合同', [original['id']])
    await run(settings, sessions, users, sent, reader())
    work = await create(client, materials=[{'attachmentId': original['id']}])
    material = (await client.get('/api/v1/work-items/' + work['id'] + '/materials')).json()['items'][0]
    copy = material['attachment']
    assert copy['id'] != original['id']
    async with sessions() as db:
        parse_job = await db.scalar(select(Job).where(Job.kind == 'document', Job.target_id == copy['id']))
    if parse_job:
        await run(settings, sessions, users, {'jobId': parse_job.id})
    current = (await client.get('/api/v1/conversations/' + conv['id'])).json()
    assert (await remove(client, 'conversations', current)).status_code == 200
    assert (await client.get(original['url'])).status_code == 404
    assert (await client.get(copy['url'])).content == real_office['sample.doc']
    for role, status in (('peer', 404), ('outsider', 404), ('admin', 200)):
        assert (await clients[role].get(copy['url'])).status_code == status
    context, current = await mode_runtime(setup, 'full', '读取保存的合同原件')
    result = json.loads(await read_work_material.coroutine(work['id'], material['id'], SimpleNamespace(context=context)))
    assert TEXT in '\n'.join(row['text'] for row in result['items'])
    async with sessions.begin() as db:
        job, source = await db.get(Job, current['jobId']), await db.get(Message, current['messageId'])
        inputs, sources = await prepare_inputs(db, users['employee'], job, source, settings, [{'attachment_id': copy['id']}])
        assert base64.b64decode(inputs[0]['data']) == real_office['sample.doc']
        assert inputs[0]['name'].endswith('.doc') and sources[0]['id'] == copy['id']


async def test_nine_mixed_old_new_office_image_and_voice_preserve_all_sources(setup, real_office, monkeypatch):
    from docx import Document
    settings, sessions, users, clients = setup
    client = clients['employee']
    modern = io.BytesIO(); document = Document(); document.add_paragraph('MODERN_OFFICE_071'); document.save(modern)
    image = io.BytesIO(); Image.new('RGB', (2, 2), 'blue').save(image, 'PNG')
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
        stream.writeframes(b'\0\0' * 1600)
    sources = [('旧材料.doc', real_office['sample.doc'], None), ('新材料.docx', modern.getvalue(), None),
               ('图.png', image.getvalue(), 'image/png'), ('语音.wav', audio.getvalue(), 'audio/wav'),
               *((f'补充-{index}.txt', f'MIXED_EXTRA_{index}'.encode(), None) for index in range(5))]
    files = [await upload(client, name, data, mime) for name, data, mime in sources]
    seen_audio, converted = [], []
    convert = documents.parse_office
    async def transcribe(context, item):
        seen_audio.append(item.id)
        return '受控语音：请保留全部来源'
    async def counted(*args, **kwargs):
        converted.append(args[1])
        return await convert(*args, **kwargs)
    monkeypatch.setattr('app.tasks.processing.asr.asr', transcribe)
    monkeypatch.setattr(documents, 'parse_office', counted)
    sent = await message(client, await conversation(client), '读取这批混合材料', [item['id'] for item in files])
    await run(settings, sessions, users, sent, reader())
    data = await refreshed(client, sent)
    assert_answered(data)
    assert [f['id'] for f in data['attachments']] == [f['id'] for f in files]
    assert seen_audio == [files[3]['id']] and converted == ['.doc']
    assert '受控语音：请保留全部来源' in data['transcript']
    assert TEXT in data['reply'] and 'MODERN_OFFICE_071' in data['reply']
    assert all(f'MIXED_EXTRA_{index}' in data['reply'] for index in range(5))
    assert {c['attachmentId'] for c in data['citations']} == {f['id'] for f in files if f['kind'] == 'document'}
    for item, (_, original, _) in zip(data['attachments'], sources):
        assert (await client.get(item['url'])).content == original
