"""Historic image batches: real pixels, bounded reads, isolation and replay."""
import base64
import hashlib
import io
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from PIL import Image

from app.agent.runtime.middleware import ToolBoundary
from app.agent.tools.catalog import available_groups
from app.agent.tools.resources.image_reads import read_images
from app.db.base import uid
from app.modules.attachments.models import Attachment
from app.modules.messages.models import Message
from app.modules.members.models import Member
from app.security.access import scope
from app.tasks.lease import lease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.streaming.publisher import ReplyPublisher
from _support.agent.business_actions import finish, runtime
from _support.agent.execution_evidence import followup
from _support.agent.work_conflict_refresh import tool_request
from _support.http.management import conversation

pytestmark = pytest.mark.asyncio


async def batches(setup, counts=(2, 1, 1), who='employee'):
    settings, sessions, users, _ = setup
    context, sent = await runtime(setup, '比较之前分批发送的图片', who=who)
    result = []
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    for batch, count in enumerate(counts):
        if batch:
            await finish(context)
            context = await followup(setup, sent['conversationId'], who=who)
        rows = []
        async with sessions.begin() as db:
            message_id = (await db.get(Job, context.job_id)).target_id
            for index in range(count):
                data = io.BytesIO()
                Image.new('RGB', (32, 32), (40 * (batch + 1), 40 * (index + 1), 80)).save(data, format='PNG')
                raw, identifier = data.getvalue(), uid()
                (settings.media_dir / identifier).write_bytes(raw)
                db.add(Attachment(id=identifier, company_id=users[who].company_id,
                                  owner_id=users[who].id, message_id=message_id,
                                  kind='image', mime='image/png', name=f'第{batch + 1}批-{index}.png',
                                  size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
                rows.append(identifier)
        result.append(rows)
    return context, result


async def read(context, identifiers=None, **kwargs):
    return json.loads(await read_images.coroutine(SimpleNamespace(context=context), attachment_ids=identifiers, **kwargs))


async def test_old_batches_are_read_together_once_and_stream_sources_stay_typed(setup, monkeypatch):
    context, groups = await batches(setup)
    identifiers = [groups[1][0], groups[0][0], groups[2][0]]
    vision = AsyncMock(return_value=AIMessage(content='三个批次的颜色不同。'))
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)
    result = await read(context, identifiers, question='比较这三张图的颜色')
    assert result['state'] == 'succeeded' and result['text'] == '三个批次的颜色不同。'
    assert [item['id'] for item in result['images']] == identifiers
    assert all(item['complete'] for item in result['images'])
    assert vision.await_count == 1
    content = vision.await_args.args[0][-1].content
    assert content[0]['text'] == '比较这三张图的颜色'
    urls = [part['image_url']['url'] for part in content if part['type'] == 'image_url']
    assert len(urls) == 3
    for url, red in zip(urls, (80, 40, 120)):
        pixel = Image.open(io.BytesIO(base64.b64decode(url.split(',')[1]))).getpixel((0, 0))
        assert abs(pixel[0] - red) <= 3
    assert set(context.image_sources) == set(identifiers) and not context.document_versions
    publisher = ReplyPublisher(context, 'historic-image-read')
    try:
        await publisher.start()
        await publisher.write(result['text'])
        await publisher.drain()
        snapshot = await publisher.store.snapshot(publisher.identity)
        assert snapshot['text'] == result['text']
        assert set(snapshot['source']['images']) == set(identifiers)
        assert snapshot['source']['documents'] == {}
    finally:
        await publisher.close()


async def test_catalog_pages_across_more_than_twenty_images_without_model_calls(setup, monkeypatch):
    context, groups = await batches(setup, (8, 8, 7))
    vision = AsyncMock()
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)
    items, pages, cursor = [], [], 0
    while cursor is not None:
        page = await read(context, start=cursor)
        assert page['state'] == 'listed'
        items.extend(page['items'])
        pages.append(len(page['items']))
        cursor = page['nextCursor']
    assert pages == [10, 10, 3]
    assert {item['id'] for item in items} == {identifier for group in groups for identifier in group}
    assert len({item['messageId'] for item in items}) == 3
    assert 'read_images' in available_groups(context)['images'] & available_groups(context)['documents']
    vision.assert_not_awaited()
    assert not context.image_sources


@pytest.mark.parametrize('invalid', ['owner', 'company', 'conversation', 'deleted_image', 'deleted_message', 'future', 'unsent', 'access'])
async def test_unavailable_images_are_not_listed_or_sent_to_model(setup, monkeypatch, invalid):
    context, groups = await batches(setup, (1, 1))
    _, sessions, users, clients = setup
    identifier = groups[0][0]
    other_conversation = await conversation(clients['employee']) if invalid == 'conversation' else None
    async with sessions.begin() as db:
        image = await db.get(Attachment, identifier)
        parent = await db.get(Message, image.message_id)
        if invalid == 'owner':
            image.owner_id = users['peer'].id
        elif invalid == 'company':
            image.company_id = users['outsider'].company_id
        elif invalid == 'conversation':
            parent.conversation_id = other_conversation['id']
        elif invalid == 'deleted_image':
            image.deleted = True
        elif invalid == 'deleted_message':
            parent.deleted = True
        elif invalid == 'future':
            current = await db.get(Message, (await db.get(Job, context.job_id)).target_id)
            parent.created_at = current.created_at + timedelta(days=1)
        elif invalid == 'unsent':
            image.message_id = None
        else:
            parent.access = {'actorId': users['employee'].id, 'companyId': users['employee'].company_id,
                             'role': 'admin', 'team': True, 'reads': {}}
    vision = AsyncMock()
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)
    page = await read(context)
    assert identifier not in {item['id'] for item in page['items']}
    denied = await read(context, [*groups[1], identifier])
    assert denied['state'] == 'unavailable' and 'images' not in denied
    assert '第1批' not in json.dumps(denied, ensure_ascii=False)
    vision.assert_not_awaited()


async def test_recovery_reuses_read_but_deleted_sources_revoke_cached_results(setup, monkeypatch):
    context, groups = await batches(setup, (1, 1))
    context.node_retry = True
    await initialize(context, 'historic-image-input')
    request = tool_request(context, 'read_images', {'attachment_ids': groups[0]}, 'image-read')
    vision = AsyncMock(return_value=AIMessage(content='已读取旧图'))
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)

    async def handler(request):
        return ToolMessage(content=await read_images.coroutine(SimpleNamespace(context=request.runtime.context), **request.tool_call['args']), name='read_images', tool_call_id='image-read')

    first = await ToolBoundary().awrap_tool_call(request, handler)
    recovered = replace(context, image_sources={}, document_versions={})
    await initialize(recovered, 'historic-image-input')
    request.runtime.context = recovered
    second = await ToolBoundary().awrap_tool_call(request, handler)
    assert json.loads(first.content)['text'] == json.loads(second.content)['text'] == '已读取旧图'
    assert vision.await_count == 1
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert {source['id'] for source in job.result['sandboxSources']} == set(groups[0])
        assert 'base64,' not in json.dumps(job.result)
        (await db.get(Attachment, groups[0][0])).deleted = True
    with pytest.raises(HTTPException):
        await ToolBoundary().awrap_tool_call(request, handler)
    async with context.sessions() as db:
        with pytest.raises(HTTPException):
            await lease(db, recovered)
    assert vision.await_count == 1


@pytest.mark.parametrize('failure', ['count', 'pixels', 'bytes', 'blocks', 'corrupt'])
async def test_oversized_or_corrupt_batch_returns_recoverable_tool_result(setup, monkeypatch, failure):
    from app.agent.tools.resources import image_reads
    context, groups = await batches(setup, (1, 1))
    vision = AsyncMock()
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)
    converted = {'pixels': 32 * 32, 'bytes': 512, 'complete': True,
                 'tiles': [{'mime': 'image/png', 'data': 'unused', 'box': [0, 0, 32, 32]}]}
    if failure == 'pixels':
        converted['pixels'] = image_reads.MAX_MESSAGE_IMAGE_PIXELS + 1
    elif failure == 'bytes':
        converted['bytes'] = image_reads.MAX_MESSAGE_IMAGE_BYTES + 1
    elif failure == 'blocks':
        converted['tiles'] *= image_reads.MAX_MESSAGE_IMAGE_BLOCKS + 1
    conversion = AsyncMock(side_effect=HTTPException(415, 'invalid image')) if failure == 'corrupt' else AsyncMock(return_value=converted)
    monkeypatch.setattr(image_reads, 'image_process', conversion)
    result = await read(context, [uid() for _ in range(10)] if failure == 'count' else groups[0])
    assert result['state'] == 'unavailable' and result['message']
    vision.assert_not_awaited()
    async with context.sessions() as db:
        await lease(db, context)


async def test_document_pages_are_discovered_in_historical_image_directory_without_vision_call(setup, monkeypatch):
    context, groups = await batches(setup, (1, 1))
    _, sessions, _, _ = setup
    identifier = groups[0][0]
    async with sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        item.kind = 'document'; item.mime = 'application/msword'; item.name = '历史材料.doc'
        item.extraction_status = 'ready'; item.extraction_revision = 1
        item.extraction_info = {'originalFormat': 'DOC', 'convertedFormat': 'DOCX', 'hasVisuals': True, 'chunks': 2, 'sourceComplete': True}
    vision = AsyncMock(side_effect=AssertionError('Discovery must not call a model'))
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)
    directory = await read(context)
    document = next(item for item in directory['items'] if item['id'] == identifier)
    assert document['kind'] == 'document'
    assert document['extraction']['originalFormat'] == 'DOC'
    assert document['extraction']['convertedFormat'] == 'DOCX'
    assert document['readPages'] == {'tool': 'read_document', 'attachment_id': identifier, 'start': 0, 'view': 'pages', 'pages': [1]}
    result = await read(context, [identifier, groups[1][0]], question='复核文档中的图表')
    assert result['state'] == 'document_pages' and result['items'][0]['id'] == identifier
    assert result['imageIds'] == groups[1] and '尚未读取像素' in result['message']
    assert not context.image_sources
    vision.assert_not_awaited()
    async with sessions.begin() as db:
        (await db.get(Attachment, identifier)).deleted = True
    assert identifier not in {item['id'] for item in (await read(context))['items']}
    assert (await read(context, [identifier]))['state'] == 'unavailable'


@pytest.mark.parametrize('mixed', [False, True])
async def test_document_redirect_inherits_all_source_access_and_revocation(setup, monkeypatch, mixed):
    context, groups = await batches(setup, (1, 1), who='admin')
    _, sessions, users, _ = setup
    identifiers = [groups[0][0], *groups[1]] if mixed else groups[0]
    expected = {}
    async with sessions.begin() as db:
        document = await db.get(Attachment, groups[0][0])
        document.kind, document.name, document.mime = 'document', '历史材料.doc', 'application/msword'
        for identifier, member in zip(identifiers, (users['employee'], users['peer'])):
            attachment = await db.get(Attachment, identifier)
            parent = await db.get(Message, attachment.message_id)
            evidence = {'type': 'member', 'id': member.id, 'ownerId': member.id}
            parent.access = {**scope(users['admin']), 'team': True, 'reads': {identifier: evidence}}
            expected[identifier] = evidence
        assert not (await db.get(Job, context.job_id)).access.get('team')
    vision = AsyncMock(side_effect=AssertionError('Redirect must not call a model'))
    monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', vision)
    result = await read(context, identifiers)
    assert result['state'] == 'document_pages'
    assert result['imageIds'] == (groups[1] if mixed else [])
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        assert job.access['team'] and job.access['reads'] == expected
        await lease(db, context)
        (await db.get(Member, users['employee'].id)).role = 'admin'
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:
            await lease(db, context)
        assert denied.value.status_code == 403
    vision.assert_not_awaited()
