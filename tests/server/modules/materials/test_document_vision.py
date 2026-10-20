"""Real upload/storage/rendering and actual BoundedChatModel input assembly."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy import select, func

from _support.http.management import conversation, message, remove
from _support.materials.documents import upload, running_context, run
from _support.materials.spec072_samples import fixture_values
from app.agent.context.document_input import assemble_pages, preload_documents, request_pages, PAGE_MARKER
from app.agent.runtime.model import BoundedChatModel
from app.agent.tools.resources.documents import read_document_result
from app.integrations.parsing.office_conversion import converter
from app.modules.attachments.documents import verified_citations
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.attachments.document_assets import generation, directory
from app.tasks.models import Job
from app.tasks.processing.documents import prepare_document
from app.tasks.context import LostLease

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope='module')
def samples():
    return fixture_values()


async def prepared(setup, samples, names):
    settings, sessions, users, clients = setup
    client = clients['employee']; conv = await conversation(client)
    items = [await upload(client, name, samples[name]) for name in names]
    async with sessions() as db:
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id.in_([item['id'] for item in items])))
    assert not (settings.media_dir / '.documents').exists()
    sent = await message(client, conv, 'Read the uploaded reference material', [item['id'] for item in items])
    context = await running_context(settings, sessions, users['employee'], sent)
    prepared = [await prepare_document(context, item['id']) for item in items]
    return context, items, prepared, conv, sent


def require_renderer():
    import shutil
    if not converter()[0] or not shutil.which('pdftoppm'):
        pytest.skip('Real LibreOffice and Poppler are required')


def model_transport(monkeypatch, captured, *, reject=False):
    from app.integrations.models.transport import ProviderError
    async def chat(settings, config, key, messages, **kwargs):
        captured.append(messages)
        if reject and len(captured) == 1:
            raise ProviderError('protocol', 'controlled image rejection', 400, image_input_unsupported=reject == 'image')
        return {'id': 'controlled-main', 'model': 'controlled', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'A bounded reference answer.'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', AsyncMock(return_value=({'streaming': False, 'protocol': 'chat'}, 'owned-test-key')))


def images(messages):
    return [b for m in messages if isinstance(m.get('content'), list) for b in m['content'] if b.get('type') == 'image_url']


async def test_search_continuation_retains_generation_citations_and_sparse_ranges(setup, samples):
    context, files, prepared_files, _, _ = await prepared(setup, samples, ['records.txt'])
    aid = files[0]['id']; revision = prepared_files[0]['extraction']['revision']
    first = json.loads(await read_document_result(context, aid, start=0, limit=1))
    citation = first['items'][0]['citation']
    search = json.loads(await read_document_result(context, aid, query='Z9P4T7', limit=3))
    assert '6842' in str(search['items']) and search['sourceComplete'] and search['nextCursor'] is None
    assert search['searchScope']['batches'] == 2 and search['searchScope']['stopReason'] == 'matches'
    assert search['searchScope']['ranges'][0][1] == search['searchScope']['ranges'][1][0]
    assert len(search['items']) == 1 and len(search['contextItems']) == 1
    search_rows = [*search['items'], *search['contextItems']]
    returned_ordinals = {row['ordinal'] for row in [*first['items'], *search_rows]}
    assert len(returned_ordinals) == 3
    assert search['readScope']['returnedChunks'] == 2
    assert search['readScope']['returnedChunksThisTask'] == len(returned_ordinals)
    async with context.sessions() as db:
        item = await db.get(Attachment, aid)
        assert item.extraction_revision == revision
        count = await db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.attachment_id == aid))
        answer, sources = await verified_citations(db, context, citation + ''.join(row['citation'] for row in search_rows))
        assert len(sources) == 3 and '变化' not in answer
    reread = json.loads(await read_document_result(context, aid, start=search['items'][0]['ordinal'], limit=1))
    assert reread['items'][0]['citation'] == search['items'][0]['citation']
    assert reread['readScope']['returnedChunksThisTask'] == len(returned_ordinals)
    async with context.sessions() as db:
        assert count == await db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.attachment_id == aid))


async def test_short_preload_budget_is_shared_and_pure_text_never_renders(setup, samples, monkeypatch):
    line_text = '\n'.join(['x' * 110] * 30 + ['TAIL'])
    context, files, prepared_files, _, sent = await prepared(setup, {**samples, 'locations.txt': line_text.encode()}, ['brief.txt', 'settings.py', 'brief.docx', 'brief.pdf', 'orders.xlsx', 'locations.txt'])
    assert not any(document['extraction']['hasVisuals'] for document in prepared_files)
    aid = files[-1]['id']
    async with context.sessions.begin() as db:
        rows = (await db.scalars(select(DocumentChunk).where(DocumentChunk.attachment_id == aid).order_by(DocumentChunk.ordinal))).all()
        assert [row.location for row in rows] == ['行 1–30 · 字符 1–3000', '行 1–30 · 字符 3001–3329', '行 31–31']
        # Mixed persisted generations must remain readable without rewriting them.
        rows[1].location = '行 1–30 · 该范围内字符 3001–3329'
        stored_locations = [row.location for row in rows]
    render = AsyncMock(side_effect=AssertionError('Pure text must not render'))
    monkeypatch.setattr('app.modules.attachments.document_assets.render_pages', render)
    blocks = [{'type': 'text', 'text': 'Question'}]
    await preload_documents(context, prepared_files, blocks)
    assert 'L8N4V6' in blocks[0]['text'] and '7319.25' in blocks[0]['text']
    assert len(blocks[0]['text']) < 12000 and len(context.document_reads) >= 5
    render.assert_not_called()
    expected = ['行 1–30 · 该范围内字符 1–3000', '行 1–30 · 该范围内字符 3001–3329', '行 31–31']
    preloads = [json.loads(value) for value in blocks[0]['text'].split('\n已提供文档正文：')[1:]]
    preload = next(value for value in preloads if value['attachment']['id'] == aid)
    result = json.loads(await read_document_result(context, aid))
    assert preload['positionBasis'] == result['positionBasis']
    assert 'location' in result['positionBasis'] and '不是原文段落号' in result['positionBasis']
    assert [row['ordinal'] for row in result['items']] == [0, 1, 2]
    assert [row['location'] for row in preload['items']] == [row['location'] for row in result['items']] == expected
    assert ''.join(row['text'] for row in result['items']) == ''.join(row['text'] for row in preload['items'])
    async with context.sessions() as db:
        answer, citations = await verified_citations(db, context, ''.join(row['citation'] for row in result['items']))
        assert '变化' not in answer and len(citations) == 3
        assert [row['location'] for row in citations] == expected
        rows = (await db.scalars(select(DocumentChunk).where(DocumentChunk.attachment_id == aid).order_by(DocumentChunk.ordinal))).all()
        assert [row.location for row in rows] == stored_locations
        from app.agent.context.references.report_context import load_materials
        source = {'messageId': sent['messageId'], 'materials': [entry for entry in context.document_reads.values() if entry[0] == aid]}
        material_rows = await load_materials(db, setup[2]['employee'], SimpleNamespace(result={'instructionSource': source}))
        assert [row['location'] for row in material_rows] == expected
    from app.modules.attachments.documents import document_chunk_location
    for location in ('第 2 页', '段落 7', '表格 1 · 行 2', '正文 · 表格 1 · 行 2 列 3 · 段落 7', '工作表「Sheet1」!A1', 'JSON /nested', '记录 2 · 至行 3'):
        assert document_chunk_location(location) == location
        expected_location = location + ' · 该范围内字符 3001–3329'
        assert document_chunk_location(location + ' · 字符 3001–3329') == expected_location
        assert document_chunk_location(expected_location) == expected_location
    # One shared budget excludes entire files rather than silently clipping them.
    from app.agent.context import document_input
    monkeypatch.setattr(document_input, 'PRELOAD_CHARACTERS', 120)
    context.document_reads.clear(); blocks = [{'type': 'text', 'text': 'Question'}]
    await preload_documents(context, prepared_files, blocks)
    assert len(context.document_reads) < 5


async def test_old_ranges_generation_is_upgraded_before_reusing_its_first_chunk(setup, samples):
    from app.integrations.parsing.document_parser import PARSER_VERSION
    context, files, prepared_files, _, _ = await prepared(setup, samples, ['brief.docx'])
    identifier = files[0]['id']; revision = prepared_files[0]['extraction']['revision']
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        item.parser_version = PARSER_VERSION.replace('ranges-v2:', 'ranges-v1:')
        item.extraction_info = {**item.extraction_info, 'hasVisuals': True}
        chunk = await db.scalar(select(DocumentChunk).where(DocumentChunk.attachment_id == identifier).order_by(DocumentChunk.ordinal))
        chunk.text = 'STALE-PARSER-CONTENT'
    result = json.loads(await read_document_result(context, identifier, start=0))
    assert 'L8N4V6' in str(result) and 'STALE-PARSER-CONTENT' not in str(result)
    async with context.sessions() as db:
        item = await db.get(Attachment, identifier)
        assert item.extraction_revision == revision + 1 and item.parser_version == PARSER_VERSION
        assert not item.extraction_info['hasVisuals']


@pytest.mark.parametrize('name', ['inspection.docx', 'workflow.pptx', 'scan.pdf', 'measurements.xlsx'])
async def test_pixels_reach_main_model_citations_are_private_and_repeat_uses_cache(setup, samples, monkeypatch, name):
    require_renderer()
    context, files, _, _, sent = await prepared(setup, samples, [name])
    sheet = 'Measurements' if name.endswith('xlsx') else ''
    result = await request_pages(context, files[0]['id'], [1], sheet=sheet)
    assert result['pageRefs'] and result['totalPages'] >= 1
    assert 'base64' not in json.dumps(result)
    captured = []; model_transport(monkeypatch, captured)
    model = BoundedChatModel(model='controlled', api_key='test', base_url='http://127.0.0.1:1', max_retries=0)
    model._run_context = context
    tool = ToolMessage(content=json.dumps(result), tool_call_id='read-page', name='read_document')
    await model._single([HumanMessage(content='Read reference material'), tool])
    assert len(images(captured[0])) >= 1 and 'data:image/' in images(captured[0])[0]['image_url']['url']
    async with context.sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert len(job.result['documentPagesProvided']) == 1
        assert 'base64,' not in json.dumps(job.result)
        _, citations = await verified_citations(db, context, result['pages'][0]['citation'] + ' [[page:invented]]')
        assert len(citations) == 1
        from app.modules.attachments.documents import delivered_citations
        prose, cards = await delivered_citations(db, context, 'A plain answer without markers.')
        assert prose == 'A plain answer without markers.' and cards == citations
    assert '[[page:' not in json.dumps(captured[0])
    client = setup[3]['employee']
    response = await client.get(citations[0]['previewUrl'])
    assert response.status_code == 200 and response.content.startswith(b'\x89PNG')
    assert (await setup[3]['peer'].get(citations[0]['previewUrl'])).status_code == 404
    monkeypatch.setattr('app.modules.attachments.document_assets.parse_office', AsyncMock(side_effect=AssertionError('Cached page must not reconvert')))
    again = await request_pages(context, files[0]['id'], [1], sheet=sheet)
    assert again['pageRefs'] == result['pageRefs']
    replay, supplied = await assemble_pages(context, [{'role': 'tool', 'content': json.dumps(again)}])
    assert images(replay) and supplied
    compacted, supplied = await assemble_pages(context, [{'role': 'user', 'content': 'Compacted reference summary without pixel references'}])
    assert not images(compacted) and not supplied


async def test_new_page_batch_takes_priority_over_old_batch_when_budget_is_full(setup, samples, monkeypatch):
    require_renderer()
    context, files, _, _, _ = await prepared(setup, samples, ['clauses.pdf'])
    old = await request_pages(context, files[0]['id'], [1])
    new = await request_pages(context, files[0]['id'], [6])
    monkeypatch.setattr('app.integrations.media.MAX_MESSAGE_IMAGE_BLOCKS', 1)
    messages = [{'role': 'tool', 'content': json.dumps(value)} for value in (old, new)]
    payload, supplied = await assemble_pages(context, messages)
    assert set(supplied) == set(new['pageRefs']) and len(images(payload)) == 1
    assert '尚未提供图片' in str(payload)
    payload, supplied = await assemble_pages(context, [*messages, messages[0]])
    assert set(supplied) == set(old['pageRefs']) and len(images(payload)) == 1
    from app.agent.context.context_usage import estimate_request
    assert estimate_request(messages) > estimate_request(messages, document_images=False) + 8000


async def test_rejected_images_degrade_once_to_text_without_false_visual_coverage(setup, samples, monkeypatch):
    require_renderer()
    context, files, _, _, sent = await prepared(setup, samples, ['scan.pdf'])
    result = await request_pages(context, files[0]['id'], [1])
    captured = []; model_transport(monkeypatch, captured, reject='image')
    model = BoundedChatModel(model='controlled', api_key='test', base_url='http://127.0.0.1:1', max_retries=0); model._run_context = context
    payload = [HumanMessage(content=[{'type': 'text', 'text': PAGE_MARKER + json.dumps(result['pageRefs'])}])]
    await model._single(payload)
    assert len(captured) == 2 and images(captured[0]) and not images(captured[1])
    assert '图片部分没读到' in str(captured[1])
    await model._single(payload)
    assert len(captured) == 3 and not images(captured[-1])
    async with context.sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert not job.result.get('documentPagesProvided')
        assert job.result['documentVisionDisabled']


@pytest.mark.parametrize('delete_original', [False, True])
async def test_cancel_after_render_before_registration_has_no_late_coverage(setup, samples, monkeypatch, delete_original):
    require_renderer()
    context, files, _, conv, sent = await prepared(setup, samples, ['scan.pdf'])
    from app.modules.attachments import document_assets
    original = document_assets.render_pages
    entered, release = asyncio.Event(), asyncio.Event()
    async def paused(*args, **kwargs):
        result = await original(*args, **kwargs); entered.set(); await release.wait(); return result
    monkeypatch.setattr(document_assets, 'render_pages', paused)
    pending = asyncio.create_task(request_pages(context, files[0]['id'], [1]))
    await asyncio.wait_for(entered.wait(), 20)
    client = setup[3]['employee']; job = (await client.get('/api/v1/jobs/' + sent['jobId'])).json()
    assert (await client.post('/api/v1/jobs/' + sent['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})).status_code == 200
    if delete_original:
        snapshot = (await client.get('/api/v1/conversations/' + conv['id'])).json()
        assert (await remove(client, 'conversations', snapshot)).status_code == 200
    release.set()
    with pytest.raises(LostLease): await pending
    if delete_original:
        assert not directory(context.settings, files[0]['id']).exists()
    async with context.sessions() as db:
        row = await db.get(Job, sent['jobId'])
        assert not row.result.get('documentPageRequests') and not row.result.get('documentPagesProvided')


async def test_saved_material_rebuilds_pages_after_original_message_deleted(setup, samples):
    require_renderer()
    from _support.work.work_records import create, key
    from _support.agent.execution_permissions import mode_runtime
    from app.agent.tools.business.work_records import read_work_material
    context, files, _, conv, _ = await prepared(setup, samples, ['inspection.docx'])
    await request_pages(context, files[0]['id'], [1])
    client = setup[3]['employee']; work = await create(client)
    saved = await client.patch('/api/v1/work-items/' + work['id'], json={'expectedRevision': 1, 'materials': [{'attachmentId': files[0]['id']}]}, headers=key())
    assert saved.status_code == 200, saved.text
    material_id = saved.json()['materialIds'][0]
    material = (await client.get(f"/api/v1/work-items/{work['id']}/materials/{material_id}")).json()
    copied = material['attachment']
    # A running message cannot be deleted until cancelled.
    job = (await client.get('/api/v1/jobs/' + context.job_id)).json()
    await client.post('/api/v1/jobs/' + context.job_id + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
    snapshot = (await client.get('/api/v1/conversations/' + conv['id'])).json()
    assert (await remove(client, 'conversations', snapshot)).status_code == 200
    assert not directory(context.settings, files[0]['id']).exists()
    new_context, _ = await mode_runtime(setup, 'full', 'Read saved material')
    result = json.loads(await read_work_material.coroutine(work['id'], material_id, SimpleNamespace(context=new_context), view='pages', pages=[1]))
    assert result['pageRefs']
    assert (await client.get(copied['url'])).content == samples['inspection.docx']
    assert (await client.get(files[0]['url'])).status_code == 404


async def test_same_content_pages_reuse_processing_but_keep_distinct_private_ids(setup, samples, monkeypatch):
    require_renderer()
    context, files, _, _, sent = await prepared(setup, samples, ['inspection.docx', 'inspection.docx'])
    first = await request_pages(context, files[0]['id'], [1])
    monkeypatch.setattr('app.modules.attachments.document_assets.parse_office', AsyncMock(side_effect=AssertionError('Identical owned page should be copied')))
    second = await request_pages(context, files[1]['id'], [1])
    assert second['pageRefs'] and first['pageRefs'] != second['pageRefs']
    async with context.sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert {ref['attachmentId'] for ref in job.result['documentPageRequests'].values()} == {item['id'] for item in files}
    current_job = (await setup[3]['employee'].get('/api/v1/jobs/' + sent['jobId'])).json()
    await setup[3]['employee'].post('/api/v1/jobs/' + sent['jobId'] + '/cancel', json={'expectedAttempt': current_job['attempt'], 'expectedFence': current_job['fence']})
    context_other, _ = await __import__('_support.agent.execution_permissions', fromlist=['mode_runtime']).mode_runtime(setup, 'full', 'Owned other message')
    # Same employee but a new unrelated conversation does not inherit the source.
    denied = json.loads(await read_document_result(context_other, files[0]['id'], view='pages'))
    assert denied['error'] == 'document_reference_unavailable'


async def test_bad_page_and_disk_failure_do_not_discard_other_pages_or_block_later_work(setup, samples, monkeypatch):
    require_renderer()
    context, files, _, _, _ = await prepared(setup, samples, ['clauses.pdf'])
    batch = await request_pages(context, files[0]['id'], [1, 999])
    assert batch['status'] == 'partial' and len(batch['pageRefs']) == 1
    assert batch['errors'][0]['page'] == 999
    from app.modules.attachments import document_assets
    native = document_assets.parse_office
    async def full_disk(*args, **kwargs):
        raise OSError(28, 'owned injected disk full')
    monkeypatch.setattr(document_assets, 'parse_office', full_disk)
    failed = await request_pages(context, files[0]['id'], [2])
    assert failed['status'] == 'partial' and not failed['pageRefs']
    async with context.sessions() as db:
        assert (await db.get(Attachment, files[0]['id'])).extraction_info.get('visualError')
    await request_pages(context, files[0]['id'], [1])
    async with context.sessions() as db:
        assert (await db.get(Attachment, files[0]['id'])).extraction_info.get('visualError')
    text = json.loads(await read_document_result(context, files[0]['id']))
    assert 'ALPHA' in str(text['items'])
    monkeypatch.setattr(document_assets, 'parse_office', native)
    recovered = await request_pages(context, files[0]['id'], [2])
    assert recovered['status'] == 'ready' and recovered['pageRefs']
    async with context.sessions() as db:
        assert not (await db.get(Attachment, files[0]['id'])).extraction_info.get('visualError')


async def test_legacy_unknown_scope_upgrades_on_demand_and_failed_upgrade_preserves_old_chunks(setup, samples, monkeypatch):
    context, files, _, _, _ = await prepared(setup, samples, ['brief.txt'])
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, files[0]['id'])
        item.parser_version = 'old-parser'; item.extraction_info = {'characters': 100, 'chunks': 1}
    from app.tasks.processing import documents
    native = documents.parse_process
    monkeypatch.setattr(documents, 'parse_process', AsyncMock(return_value={'status': 'failed', 'chunks': [], 'info': {'error': 'owned parser fault'}}))
    result = json.loads(await read_document_result(context, files[0]['id']))
    assert result['items'] and 'L8N4V6' in str(result['items'])
    async with context.sessions() as db:
        item = await db.get(Attachment, files[0]['id'])
        assert item.extraction_revision == 1 and item.parser_version == 'old-parser'
    monkeypatch.setattr(documents, 'parse_process', native)
    upgraded = json.loads(await read_document_result(context, files[0]['id']))
    assert upgraded['sourceComplete'] and 'L8N4V6' in str(upgraded['items'])
    async with context.sessions() as db:
        item = await db.get(Attachment, files[0]['id'])
        assert item.extraction_revision == 2 and item.extraction_info['schema'] == 1


async def test_generic_protocol_error_never_silently_drops_document_images(setup, samples, monkeypatch):
    require_renderer()
    from app.integrations.models.transport import ProviderError, structured_error
    explicit = structured_error({'error': {'type': 'invalid_request_error', 'message': 'This model does not support image input.'}}, status=400)
    generic = structured_error({'error': {'type': 'invalid_request_error', 'message': 'Invalid max_tokens for this model'}}, status=400)
    assert explicit.image_input_unsupported and not generic.image_input_unsupported
    assert not structured_error({'error': {'code': 'invalid_api_key', 'message': 'does not support image'}}, status=403).image_input_unsupported
    context, files, _, _, sent = await prepared(setup, samples, ['scan.pdf'])
    result = await request_pages(context, files[0]['id'], [1])
    captured = []; model_transport(monkeypatch, captured, reject='generic')
    model = BoundedChatModel(model='controlled', api_key='test', base_url='http://127.0.0.1:1', max_retries=0); model._run_context = context
    with pytest.raises(ProviderError):
        await model._single([HumanMessage(content=[{'type': 'text', 'text': PAGE_MARKER + json.dumps(result['pageRefs'])}])])
    assert len(captured) == 1 and images(captured[0])
    async with context.sessions() as db:
        assert not (await db.get(Job, sent['jobId'])).result.get('documentVisionDisabled')


async def test_derivative_storage_and_cleanup_follow_attachment_lifecycle(setup, samples, monkeypatch):
    require_renderer()
    context, files, _, conv, sent = await prepared(setup, samples, ['clauses.pdf'])
    result = await request_pages(context, files[0]['id'], [1])
    from app.agent.context.document_input import record_page_delivery
    _, supplied = await assemble_pages(context, [{'role': 'tool', 'content': json.dumps(result)}])
    await record_page_delivery(context, supplied)
    async with context.sessions() as db:
        _, citations = await verified_citations(db, context, result['pages'][0]['citation'])
        item = await db.get(Attachment, files[0]['id'])
    ready_path = generation(context.settings, item)
    # Cross both former cumulative quotas without actually filling the disk.
    filler = ready_path / 'owned-capacity.bin'
    with filler.open('wb') as stream: stream.truncate(11 * 1024 * 1024 * 1024)
    assert (await request_pages(context, files[0]['id'], [2]))['pageRefs']
    client = setup[3]['employee']
    assert (await client.get(citations[0]['previewUrl'])).status_code == 200
    from app.modules.attachments import document_assets
    with monkeypatch.context() as disk:
        disk.setattr(document_assets.shutil, 'disk_usage', lambda _: SimpleNamespace(free=512 * 1024 * 1024))
        failed = await request_pages(context, files[0]['id'], [3])
        assert failed['status'] == 'partial' and not failed['pageRefs']
        assert (await client.get(citations[0]['previewUrl'])).status_code == 200
    assert (await request_pages(context, files[0]['id'], [3]))['pageRefs']
    assert filler.is_file()  # Valid derivatives survive reads, including low disk space.
    job = (await client.get('/api/v1/jobs/' + sent['jobId'])).json()
    await client.post('/api/v1/jobs/' + sent['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
    snapshot = (await client.get('/api/v1/conversations/' + conv['id'])).json()
    native = document_assets.remove
    def fault(settings, identifier):
        if identifier == files[0]['id']: raise PermissionError('owned cleanup failure')
        return native(settings, identifier)
    monkeypatch.setattr(document_assets, 'remove', fault)
    assert (await remove(client, 'conversations', snapshot)).status_code == 503
    assert (await client.get(citations[0]['previewUrl'])).status_code == 404
    assert ready_path.exists()  # Not publicly accessible after tombstoning.
    monkeypatch.setattr(document_assets, 'remove', native)
    assert (await remove(client, 'conversations', snapshot)).status_code == 200
    assert not directory(context.settings, files[0]['id']).exists()
    assert not (context.settings.media_dir / files[0]['id']).exists()
    async with context.sessions() as db:
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id == files[0]['id']))


async def test_four_accounts_fast_slow_and_failed_worker_preparation_remain_isolated(setup, samples, monkeypatch):
    require_renderer()
    from _support.agent.fakes import controlled_model
    from _support.materials.legacy_samples import legacy_samples
    from app.tasks.processing import documents
    settings, sessions, users, clients = setup
    raw = legacy_samples()['sample.doc']
    started, release = asyncio.Event(), asyncio.Event()
    native = documents.parse_office
    async def slow_failure(*args, **kwargs):
        # The real conversion finishes; injected storage failure happens afterward.
        result = await native(*args, **kwargs)
        assert result['status'] in ('ready', 'partial')
        started.set(); await release.wait()
        raise OSError(28, 'owned injected storage failure')
    monkeypatch.setattr(documents, 'parse_office', slow_failure)
    sent, files = {}, {}
    for role, name, data in [('employee', 'slow.doc', raw), ('peer', 'peer.txt', b'PEER-ONLY-19'), ('admin', 'admin.txt', b'ADMIN-ONLY-42'), ('outsider', 'scan.pdf', samples['scan.pdf'])]:
        files[role] = await upload(clients[role], name, data)
        sent[role] = await message(clients[role], await conversation(clients[role]), 'Read only my attachment', [files[role]['id']])
    tasks = {role: asyncio.create_task(run(settings, sessions, users, value, controlled_model('clarify'))) for role, value in sent.items()}
    try:
        await asyncio.wait_for(started.wait(), 20)
        await asyncio.wait_for(asyncio.gather(tasks['peer'], tasks['admin']), 10)
        for role in ('peer', 'admin'):
            view = (await clients[role].get('/api/v1/messages/' + sent[role]['messageId'])).json()
            assert view['reply'] and view['attachments'][0]['extraction']['status'] == 'ready'
        # Authorization/login state stays available while another account's native slot is held.
        for role in clients:
            assert (await clients[role].get('/api/v1/auth/me')).status_code == 200
        assert not tasks['employee'].done()
    finally:
        release.set(); await asyncio.gather(*tasks.values())
    for role in clients:
        view = (await clients[role].get('/api/v1/messages/' + sent[role]['messageId'])).json()
        assert view['reply'] and len(view['attachments']) == 1
        assert view['attachments'][0]['id'] == files[role]['id']
        for other in clients:
            if other != role:
                assert (await clients[other].get(files[role]['url'])).status_code == 404
    failed = (await clients['employee'].get('/api/v1/messages/' + sent['employee']['messageId'])).json()
    assert failed['attachments'][0]['extraction']['status'] == 'failed'
    for role in ('employee', 'outsider'):
        next_message = await message(clients[role], await conversation(clients[role]), 'ordinary followup')
        await run(settings, sessions, users, next_message, controlled_model('clarify'))
        assert (await clients[role].get('/api/v1/messages/' + next_message['messageId'])).json()['reply']


@pytest.mark.parametrize('modern,legacy', [('inspection.docx', 'doc'), ('workflow.pptx', 'ppt')])
async def test_real_legacy_mixed_original_converts_and_provides_pixels(setup, samples, tmp_path, modern, legacy):
    require_renderer()
    import subprocess
    from app.integrations.parsing.office_conversion import environment
    original = tmp_path / modern; original.write_bytes(samples[modern])
    output = await asyncio.to_thread(subprocess.run, [converter()[0], '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(), '--headless', '--convert-to', legacy, '--outdir', str(tmp_path), str(original)], capture_output=True, timeout=30, env=environment())
    source = original.with_suffix('.' + legacy)
    assert output.returncode == 0 and source.is_file()
    context, files, prepared_files, _, _ = await prepared(setup, {source.name: source.read_bytes()}, [source.name])
    assert prepared_files[0]['extraction']['status'] in ('ready', 'partial')
    result = await request_pages(context, files[0]['id'], [1])
    payload, supplied = await assemble_pages(context, [{'role': 'tool', 'content': json.dumps(result)}])
    assert images(payload) and supplied and result['totalPages'] >= 1
    assert (await setup[3]['employee'].get(files[0]['url'])).content == source.read_bytes()


async def test_multiple_upload_batches_history_merge_deliverable_and_refresh(setup, monkeypatch):
    from _support.agent.fakes import controlled_model, ReviewedFixtureModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.tasks.processing.handlers import process_job
    from app.tasks.runtime.queue import claim
    from pydantic import Field
    from io import BytesIO
    import wave
    stream = BytesIO()
    with wave.open(stream, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\0' * 3200)
    settings, sessions, users, clients = setup
    client = clients['employee']; conv = await conversation(client)
    expected, first_ids = [], []
    async def execute(sent, model):
        job = await claim(sessions, users['employee'].id)
        assert job.id == sent['jobId']
        async def asr(_context, item): return 'Audio reference only ' + item.name
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            await process_job(job, sessions, settings, saver, model=model, asr_provider=asr)
    for batch in range(2):
        values = []
        for index in range(6):
            fact = f'PRIVATE-BATCH-{batch}-ITEM-{index}'
            expected.append(fact)
            values.append(await upload(client, f'notes-{index}.txt', fact.encode()))
        import io
        from PIL import Image
        picture = io.BytesIO(); Image.new('RGB', (20, 20), (50 * batch, 10, 20)).save(picture, 'PNG')
        values.append(await upload(client, 'picture.png', picture.getvalue(), 'image/png'))
        values.append(await upload(client, f'reference-{batch}.wav', stream.getvalue(), 'audio/wav'))
        if batch == 0: first_ids = [value['id'] for value in values]
        sent = await message(client, conv, 'Keep these references for later', [value['id'] for value in values])
        await execute(sent, controlled_model('clarify'))
        assert (await client.get('/api/v1/messages/' + sent['messageId'])).json()['reply']
    from _support.materials.document_fakes import DocumentFixtureModel
    class BatchModel(DocumentFixtureModel):
        sources: list = Field(default_factory=list)
        async def _agenerate(self, messages, **kwargs):
            def call(name, args, ident=None):
                return {'id': ident or 'batch-' + name, 'name': name, 'args': args}
            last = messages[-1]
            if not isinstance(last, ToolMessage):
                reply = AIMessage(content='', tool_calls=[call('load_tools', {'groups': ['documents']})])
            elif last.name == 'load_tools':
                reply = AIMessage(content='', tool_calls=[call('find_documents', {'query': ''})])
            elif last.name == 'find_documents':
                result = json.loads(last.content); self.sources.extend(result['items'])
                if result['nextCursor'] is not None:
                    reply = AIMessage(content='', tool_calls=[call('find_documents', {'query': '', 'start': result['nextCursor']}, 'directory-next')])
                else:
                    reply = AIMessage(content='', tool_calls=[call('read_document', {'attachment_id': row['id'], 'start': 0}, 'read-' + row['id']) for row in self.sources[:4]])
            elif last.name == 'read_document':
                results = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage) and m.name == 'read_document']
                seen = {value['attachment']['id'] for value in results}
                pending = [row for row in self.sources if row['id'] not in seen]
                if pending:
                    reply = AIMessage(content='', tool_calls=[call('read_document', {'attachment_id': row['id'], 'start': 0}, 'read-' + row['id']) for row in pending[:4]])
                else:
                    body = '\n'.join(row['text'] for value in results for row in value['items'])
                    reply = AIMessage(content='', tool_calls=[call('save_deliverable', {'title': 'Merged reference memo', 'body': body})])
            else:
                assert last.name == 'save_deliverable', last
                result = json.loads(last.content)
                assert result['state'] == 'succeeded', result
                results = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage) and m.name == 'read_document']
                reply = AIMessage(content=result['body'])
            return ChatResult(generations=[ChatGeneration(message=reply)])
    sent = await message(client, conv, 'Read every document from both batches and save a merged reference memo')
    model = BatchModel(model='controlled-batches', api_key='test', base_url='http://127.0.0.1:1', max_retries=0)
    await execute(sent, model)
    detail = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['state'] == 'succeeded', detail
    assert all(fact in detail['reply'] for fact in expected)
    assert len(detail['citations']) == 12 and detail['deliverables']
    saved = (await client.get('/api/v1/deliverables/' + detail['deliverables'][0]['id'])).json()
    assert all(fact in saved['body'] for fact in expected)
    # A fresh job/context can still re-fetch the earliest material after UI refresh.
    following = await message(client, conv, 'Read the first original again')
    context = await running_context(settings, sessions, users['employee'], following)
    result = json.loads(await read_document_result(context, first_ids[0]))
    assert expected[0] in str(result['items'])
    assert (await clients['peer'].get('/api/v1/messages/' + sent['messageId'])).status_code == 404


async def test_returned_fragment_scope_does_not_inherit_complete_extraction(setup, samples):
    context, files, _, _, _ = await prepared(setup, samples, ['records.txt'])
    identifier = files[0]['id']
    first = json.loads(await read_document_result(context, identifier, start=0, limit=1))
    assert first['readScope']['returnedChunks'] == 1
    assert first['readScope']['extractedChunks'] > 1
    assert not first['readScope']['allExtractedTextReturned']
    assert 'allExtractableTextReturned' not in first['readScope']
    assert not first['readScope']['pageImagesIncluded']
    assert first['attachment']['readText']['attachment_id'] == identifier


async def test_tool_read_scope_counts_unique_current_revision_returns_not_search_scope(setup, samples):
    from app.agent.context.document_input import record_text_delivery
    context, files, _, _, _ = await prepared(setup, samples, ['records.txt'])
    identifier = files[0]['id']
    first = json.loads(await read_document_result(context, identifier, start=0, limit=1))
    assert first['readScope']['returnedChunksThisTask'] == 1
    assert first['readScope']['providedChunksBeforeThisCall'] == 0
    await record_text_delivery(context, [{'role': 'tool', 'content': json.dumps(first)}])
    repeated = json.loads(await read_document_result(context, identifier, start=0, limit=1))
    assert repeated['readScope']['returnedChunksThisTask'] == 1
    assert repeated['readScope']['providedChunksBeforeThisCall'] == 1
    empty = json.loads(await read_document_result(context, identifier, query='ABSENT-FACT', limit=3))
    assert empty['readScope']['returnedChunks'] == 0
    assert empty['readScope']['returnedChunksThisTask'] == 1
    assert empty['readScope']['unreturnedExtractedChunksThisTask'] == empty['readScope']['extractedChunks'] - 1
    assert empty['readScope']['limitations']
    context.document_reads['old-revision'] = (identifier, 0, 777)
    following = json.loads(await read_document_result(context, identifier, start=1, limit=1))
    assert following['readScope']['returnedChunksThisTask'] == 2
    assert following['readScope']['providedChunksBeforeThisCall'] == 1


async def test_preload_retains_conversion_uncertainty_and_structural_table_receipt(setup, samples, monkeypatch):
    from app.modules.attachments.documents import document_reference, attachment_dto, prepared_document_reference
    context, files, prepared_files, _, _ = await prepared(setup, samples, ['brief.docx', 'register.xlsx'])
    identifier = files[0]['id']
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        item.extraction_info = {**item.extraction_info, 'originalFormat': 'doc', 'convertedFormat': 'docx'}
        prepared_files[0] = attachment_dto(item)
        reference = document_reference(item)
        assert reference['extraction']['hasVisuals'] is None
        assert not reference['extraction']['conversionFidelityVerified']
        assert reference['readPages']['attachment_id'] == identifier
        assert prepared_document_reference(prepared_files[0], message_id=item.message_id) == reference
        assert prepared_files[0]['extraction']['hasVisuals'] is False
    render = AsyncMock(side_effect=AssertionError('Do not add automatic conversion or page rendering'))
    monkeypatch.setattr('app.modules.attachments.document_assets.render_pages', render)
    blocks = [{'type': 'text', 'text': 'Read'}]
    await preload_documents(context, prepared_files, blocks)
    receipts = [json.loads(piece) for piece in blocks[0]['text'].split('已提供文档正文：')[1:]]
    converted = next(value for value in receipts if value['attachment']['id'] == identifier)
    assert converted['readScope']['textBasis'] == 'converted_text'
    assert converted['attachment']['extraction']['convertedFormat'] == 'docx'
    assert converted['readScope']['allExtractedTextReturned']
    assert 'allExtractableTextReturned' not in converted['readScope']
    assert 'scope' not in converted  # readScope is the one reading receipt.
    assert any('未核验' in text for text in converted['readScope']['limitations'])
    spreadsheet = next(value for value in receipts if value['attachment']['id'] == files[1]['id'])
    stats = spreadsheet['tableStructure']['sheets'][0]
    assert stats['lastContentRow'] == 22050
    assert stats['visibleRowsWithoutValuesBetween'] == 22048
    assert stats['visibleContentCells'] == 3
    assert stats['hiddenRowsPresent'] is False and stats['hiddenColumnsPresent'] is False
    assert stats['hiddenContentStatus'] == 'not_present'
    assert 'hiddenRowsExcluded' not in stats and '隐藏内容未读' not in spreadsheet['tableStructure']['basis']
    render.assert_not_called()


@pytest.mark.parametrize('converted', [False, True])
async def test_worker_initial_model_input_uses_same_document_contract_as_tools(setup, monkeypatch, converted):
    from _support.agent.fakes import ReviewedFixtureModel, completion
    from app.modules.attachments.documents import document_reference
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import Field
    if converted:
        require_renderer()
    settings, sessions, users, clients = setup
    client = clients['employee']; conv = await conversation(client)
    raw = b'{\\rtf1\\ansi Reference READ-42.}' if converted else b'Reference READ-42.'
    file = await upload(client, 'reference.rtf' if converted else 'reference.txt', raw)
    sent = await message(client, conv, 'Read the reference in this file.', [file['id']])
    render = AsyncMock(side_effect=AssertionError('Metadata projection must not request page rendering'))
    monkeypatch.setattr('app.modules.attachments.document_assets.render_pages', render)

    class InputModel(ReviewedFixtureModel):
        captured: list = Field(default_factory=list, exclude=True)

        async def _agenerate(self, messages, **kwargs):
            self.captured.append(messages)
            return ChatResult(generations=[ChatGeneration(message=completion('The reference is READ-42.'))])

    model = InputModel(model='controlled-input-contract', api_key='test', base_url='http://127.0.0.1:1')
    await run(settings, sessions, users, sent, model)
    detail = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['phase'] == 'complete' and detail['job']['taskOutcome']['state'] == 'completed', detail
    assert 'READ-42' in detail['reply'] and not detail['job']['error']
    assert len(model.captured) == 1
    blocks = next(m.content for m in model.captured[0] if isinstance(m, HumanMessage) and isinstance(m.content, list))
    text = '\n'.join(block.get('text', '') for block in blocks)
    directory_line = next(line for line in text.splitlines() if line.startswith('本次文档目录'))
    entry = json.loads(directory_line.split('：', 1)[1])[0]
    preloaded = json.loads(text.split('已提供文档正文：', 1)[1])
    async with sessions() as db:
        item = await db.get(Attachment, file['id'])
        assert entry == document_reference(item)
    assert entry['messageId'] == sent['messageId']
    assert text.startswith('服务端当前消息 ID（messageId）：' + sent['messageId'] + '\n用户正文：\n')
    assert '原消息 ID' not in text
    assert 'extractionMeaning' not in entry
    assert entry['readText']['attachment_id'] == file['id']
    assert 'url' not in entry and 'size' not in entry
    assert 'allExtractableTextReturned' not in preloaded['readScope']
    assert preloaded['readScope']['allExtractedTextReturned']
    if converted:
        assert detail['attachments'][0]['extraction']['hasVisuals'] is False
        assert entry['extraction']['hasVisuals'] is None
        assert entry['extraction']['conversionFidelityVerified'] is False
        assert entry['readPages']['attachment_id'] == file['id']
        assert preloaded['attachment']['extraction']['hasVisuals'] is None
        assert preloaded['readScope']['textBasis'] == 'converted_text'
        assert any('未核验' in value for value in preloaded['readScope']['limitations'])
    else:
        assert entry['extraction']['hasVisuals'] is False
        assert 'readPages' not in entry
        assert preloaded['readScope']['textBasis'] == 'extracted_text'
    render.assert_not_called()


@pytest.mark.parametrize('flags,expected', [
    ({'hiddenRowsExcluded': False, 'hiddenColumnsExcluded': False}, (False, False, 'not_present')),
    ({'hiddenRowsExcluded': True, 'hiddenColumnsExcluded': False}, (True, False, 'not_read')),
    ({'hiddenRowsExcluded': False, 'hiddenColumnsExcluded': True}, (False, True, 'not_read')),
    ({}, (None, None, 'unknown')),
    ({'hiddenRowsExcluded': False}, (False, None, 'unknown')),
])
async def test_stored_table_projection_preserves_unknown_hidden_regions(flags, expected):
    from copy import deepcopy
    from app.modules.attachments.documents import table_structure_reference
    info = {'tableStructure': {'basis': '隐藏内容未读', 'sheets': [
        {'sheet': 'Data', 'visibleContentRows': 2, **flags}], 'omittedSheets': 0}}
    stored = deepcopy(info)
    projected = table_structure_reference(info)
    row = projected['sheets'][0]
    assert (row['hiddenRowsPresent'], row['hiddenColumnsPresent'], row['hiddenContentStatus']) == expected
    assert 'hiddenRowsExcluded' not in row and 'hiddenColumnsExcluded' not in row
    assert row['visibleContentRows'] == 2 and projected['omittedSheets'] == 0
    assert info == stored
    assert table_structure_reference({}) is None
