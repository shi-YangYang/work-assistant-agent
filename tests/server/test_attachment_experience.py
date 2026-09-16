import asyncio
import base64
from datetime import timedelta
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from paa_server.documents import parse_process
from paa_server.media import image_process, audio_mime, audio_wav, preview_path
from paa_server.models import Attachment, Job, Message, now
from paa_server.worker import process_job, maintenance
from attachment_samples import image_samples, spreadsheet_bytes, mp3_bytes
from test_company import keyed
from test_documents import upload
from test_management import conversation, message, remove
from fakes import controlled_model

pytestmark = pytest.mark.asyncio


async def test_images_correct_orientation_alpha_detail_and_bound_coverage(tmp_path):
    originals = image_samples()
    for name, data in originals.items():
        path = tmp_path / name; path.write_bytes(data)
        result = await image_process(path, 'model')
        assert path.read_bytes() == data
        assert result['pixels'] <= 8_000_000 and result['bytes'] <= 3 * 1024 * 1024
        assert len(result['tiles']) <= 4
        first = result['tiles'][0]
        decoded = Image.open(io.BytesIO(base64.b64decode(first['data'])))
        assert not decoded.getexif()
        if name == 'rotated.jpg':
            assert decoded.size == (80, 160)
            assert decoded.getpixel((20, 20))[0] > 200
        elif name == 'transparent.png':
            assert decoded.getpixel((400, 150)) == (255, 255, 255)
            assert first['mime'] == 'image/png'
        elif name == 'screenshot.png':
            assert decoded.size == (500, 1800) and result['complete']
            assert decoded.tobytes() == Image.open(io.BytesIO(data)).tobytes()
        elif name == 'long.png':
            assert not result['complete'] and len(result['tiles']) == 4
            assert [tile['box'][1] for tile in result['tiles']] == [0, 2048, 4096, 6144]
            assert '未读取' in ' '.join(result['warnings'])
        elif name == 'phone.heic':
            assert result['mime'] == 'image/heic' and decoded.size == (160, 80)
    oversized = tmp_path / 'oversized.png'
    Image.new('1', (5000, 4001)).save(oversized)
    with pytest.raises(HTTPException) as failed: await image_process(oversized)
    assert failed.value.status_code == 415
    bad = tmp_path / 'bad.heic'; bad.write_bytes(b'not heic')
    with pytest.raises(HTTPException): await image_process(bad)


async def test_xlsx_preserves_addresses_saved_values_hidden_ranges_and_limits(tmp_path):
    path = tmp_path / 'progress.xlsx'; path.write_bytes(spreadsheet_bytes())
    result = await parse_process(path, '.xlsx')
    assert result['status'] == 'partial', result
    text = '\n'.join(chunk['text'] for chunk in result['chunks'])
    assert 'D2：=B2+2；文件保存值（非实时计算）：5' in text
    assert 'E2：=B2+7；文件未保存计算结果，未计算' in text
    assert '2026-09-16' in text and '错误值：#DIV/0!' in text
    assert 'A6:C6' in text and '合并说明' in text
    assert all(secret not in text for secret in ('隐藏行秘密', '隐藏列秘密', '隐藏表秘密'))
    assert any('项目进度」!A2:F2' in chunk['location'] for chunk in result['chunks'])
    assert any('隐藏' in warning for warning in result['info']['warnings'])
    # Forged dimensions cannot hide cells; physical far-away cells are bounded.
    from openpyxl import Workbook
    workbook = Workbook(); workbook.active['A1'] = '可读'; workbook.active['XFD1048576'] = '超界'
    workbook.save(path)
    result = await parse_process(path, '.xlsx')
    assert result['status'] == 'partial' and '可读' in str(result['chunks'])
    assert '超界' not in str(result['chunks'])
    assert '未读取' in str(result['info']['warnings'])
    path.write_bytes(b'PK\x03\x04broken')
    assert (await parse_process(path, '.xlsx'))['status'] == 'failed'


async def test_mp3_real_decode_and_mixed_message_single_task_and_asr_failure(setup, tmp_path, monkeypatch):
    settings, sessions, users, c = setup
    original = mp3_bytes(tmp_path, settings.ffmpeg)
    assert audio_mime(original[:16]) == 'audio/mpeg'
    path = tmp_path / 'audio'; path.write_bytes(original)
    wav, duration = await audio_wav(path, settings)
    assert wav.startswith(b'RIFF') and 0 < duration < 1
    audio = await upload(c['employee'], 'voice.mp3', original, 'audio/mpeg')
    image = await upload(c['employee'], 'transparent.png', image_samples()['transparent.png'], 'image/png')
    doc = await upload(c['employee'], 'progress.xlsx', spreadsheet_bytes())
    conv = await conversation(c['employee'])
    body = {'conversationId': conv['id'], 'text': '查看本次现场材料', 'attachmentIds': [image['id'], doc['id'], audio['id']]}
    headers = keyed()
    sent = await c['employee'].post('/api/v1/messages', json=body, headers=headers)
    assert sent.status_code == 202, sent.text
    assert (await c['employee'].post('/api/v1/messages', json=body, headers=headers)).json() == sent.json()
    import paa_server.worker as worker
    from paa_server.agent.harness import get_message_context
    received = []
    original_harness = worker.invoke_harness
    async def inspect_input(context, saver, blocks, model):
        source = json.loads(await get_message_context.coroutine(message_id=sent.json()['messageId'], runtime=SimpleNamespace(context=context)))
        received.append((blocks[0]['text'], source))
        return await original_harness(context, saver, blocks, model)
    monkeypatch.setattr(worker, 'invoke_harness', inspect_input)
    async def execute(provider):
        async with sessions.begin() as db:
            job = await db.get(Job, sent.json()['jobId']); job.state = 'running'; job.fence += 1; job.lease_until = now() + timedelta(seconds=90)
        model = controlled_model('clarify')
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            await process_job(job, sessions, settings, saver, model=model, asr_provider=provider)
        return model
    async def failed(*_): raise ValueError('受控语音识别失败')
    model = await execute(failed)
    result = (await c['employee'].get('/api/v1/messages/' + sent.json()['messageId'])).json()
    assert result['job']['state'] == 'failed' and not result['reply'] and len(result['attachments']) == 3
    assert not model.seen_images
    async def recognized(*_): return '今天完成现场检查，附件是进度资料'
    model = await execute(recognized)
    result = (await c['employee'].get('/api/v1/messages/' + sent.json()['messageId'])).json()
    assert result['job']['state'] == 'awaiting_input', result
    assert result['transcript'] == '今天完成现场检查，附件是进度资料'
    assert model.seen_images and next(a for a in result['attachments'] if a['kind'] == 'document')['extraction']['status'] == 'partial'
    prompt, source = received[-1]
    inventory = json.loads(prompt.split('本次完整附件清单（已上传的原始材料；不代表所有内容均已读取）：', 1)[1].split('\n', 1)[0])
    assert {item['id']: item for item in inventory} == {item['id']: item for item in source['attachments']}
    assert {item['id'] for item in inventory} == {image['id'], doc['id'], audio['id']}
    voice = next(item for item in inventory if item['kind'] == 'audio')
    assert voice == {'id': audio['id'], 'name': 'voice.mp3', 'kind': 'audio', 'uploadStatus': 'received', 'transcription': {'status': 'available', 'revision': 1}}
    audio_source = json.loads(prompt.split('语音内容来源：', 1)[1].split('\n', 1)[0])
    assert audio_source['receivedAudioFiles'] == ['voice.mp3'] and audio_source['transcript'] == source['transcript']
    assert [item['id'] for item in source['documents']] == [doc['id']]
    assert '今天完成现场检查，附件是进度资料' in prompt and source['transcript'] in prompt
    assert '仅含文档，不含图片和语音' in prompt
    # Reprocessing a corrected transcript preserves its source and never repeats ASR.
    async with sessions.begin() as db:
        row = await db.get(Message, sent.json()['messageId'])
        row.transcript, row.transcript_revision = '纠正：现场检查尚未完成', 2
    await execute(failed)
    result = (await c['employee'].get('/api/v1/messages/' + sent.json()['messageId'])).json()
    assert result['job']['state'] == 'awaiting_input', result
    prompt, source = received[-1]
    assert '纠正：现场检查尚未完成' in prompt and source['transcript'] in prompt
    assert next(item for item in source['attachments'] if item['kind'] == 'audio')['transcription']['revision'] == 2
    second = await upload(c['employee'], 'second.mp3', original, 'audio/mpeg')
    third = await upload(c['employee'], 'third.mp3', original, 'audio/mpeg')
    rejected = await c['employee'].post('/api/v1/messages', json={'text': 'two voices', 'attachmentIds': [second['id'], third['id']]}, headers=keyed())
    assert rejected.status_code == 422


async def test_preview_auth_original_concurrency_delete_and_orphan_cleanup(setup, monkeypatch):
    settings, sessions, users, c = setup
    raw = image_samples()['phone.heic']
    item = await upload(c['employee'], 'phone.heic', raw, 'image/heic')
    assert item['previewUrl'] and item['image']['width'] == 160
    for role in ('peer', 'outsider', 'admin'):
        assert (await c[role].get(item['previewUrl'])).status_code == 404
    previews = await asyncio.gather(*(c['employee'].get(item['previewUrl']) for _ in range(2)))
    assert all(response.status_code == 200 for response in previews)
    assert previews[0].content == previews[1].content
    assert previews[0].headers['cache-control'] == 'private, no-store'
    assert (await c['employee'].get(item['url'])).content == raw
    conv = await conversation(c['employee'], '附件预览'); await message(c['employee'], conv, '', [item['id']])
    assert (await c['admin'].get(item['previewUrl'])).status_code == 200
    assert (await remove(c['employee'], 'conversations', conv)).status_code == 200
    assert (await c['employee'].get(item['previewUrl'])).status_code == 404
    await maintenance(sessions, settings)
    assert not preview_path(settings, item['id']).exists()
    # Force deletion while an uncached conversion is in flight; no resurrection.
    second = await upload(c['employee'], 'phone.heic', raw, 'image/heic')
    next_conv = await conversation(c['employee'], '附件预览'); await message(c['employee'], next_conv, '', [second['id']])
    import paa_server.api as api_module
    started, resume = asyncio.Event(), asyncio.Event()
    original_process = api_module.image_process
    async def delayed(path, mode='validate'):
        result = await original_process(path, mode)
        if mode == 'preview': started.set(); await resume.wait()
        return result
    monkeypatch.setattr(api_module, 'image_process', delayed)
    request = asyncio.create_task(c['employee'].get(second['previewUrl']))
    await asyncio.wait_for(started.wait(), 10)
    assert (await remove(c['employee'], 'conversations', next_conv)).status_code == 200
    resume.set()
    assert (await request).status_code == 404
    assert not preview_path(settings, second['id']).exists()
    orphan = await upload(c['employee'], 'phone.heic', raw, 'image/heic')
    assert (await c['employee'].get(orphan['previewUrl'])).status_code == 200
    async with sessions.begin() as db:
        row = await db.get(Attachment, orphan['id']); row.created_at = now() - timedelta(hours=25)
    await maintenance(sessions, settings)
    assert not preview_path(settings, orphan['id']).exists()
    assert not (settings.media_dir / orphan['id']).exists()


async def test_preview_rejects_logout_while_conversion_is_in_flight(setup, monkeypatch):
    settings, sessions, users, clients = setup
    item = await upload(clients['employee'], 'phone.heic', image_samples()['phone.heic'], 'image/heic')
    import paa_server.api as api_module
    started, resume = asyncio.Event(), asyncio.Event()
    original = api_module.image_process
    async def delayed(path, mode='validate'):
        result = await original(path, mode)
        started.set()
        await resume.wait()
        return result
    monkeypatch.setattr(api_module, 'image_process', delayed)
    request = asyncio.create_task(clients['employee'].get(item['previewUrl']))
    try:
        await asyncio.wait_for(started.wait(), 10)
        assert (await clients['employee'].post('/api/v1/auth/logout')).status_code == 200
        resume.set()
        assert (await request).status_code == 401
        assert not preview_path(settings, item['id']).exists()
    finally:
        resume.set()
        if not request.done(): request.cancel()
        await asyncio.gather(request, return_exceptions=True)
