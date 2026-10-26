"""Follow-up source evidence is carried, never inferred from assistant prose."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from _support.http.management import conversation, message
from _support.materials.documents import running_context, upload
from app.agent.context.document_input import project_document_messages, record_text_delivery
from app.agent.context.history import conversation_history
from app.agent.tools.resources.documents import read_document_result
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.messages.models import Message
from app.tasks.models import Job
from app.tasks.processing.documents import prepare_document

pytestmark = pytest.mark.asyncio


async def followup(setup, *, delivered=True):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    attachment = await upload(clients['employee'], 'source.txt', b'quantity: 12\nstatus: pending shipment\n' + b'x' * 6400)
    first = await message(clients['employee'], conv, 'Read this file', [attachment['id']])
    before = await running_context(settings, sessions, users['employee'], first)
    await prepare_document(before, attachment['id'])
    receipt = json.loads(await read_document_result(before, attachment['id'], limit=1))
    if delivered:
        await record_text_delivery(before, [{'role': 'tool', 'name': 'read_document', 'content': json.dumps(receipt)}])
    async with sessions.begin() as db:
        job = await db.get(Job, first['jobId']); job.state = 'succeeded'
        original = await db.get(Message, first['messageId']); original.reply = 'Unverified assistant claims are not source text.'
    second = await message(clients['employee'], conv, 'What was its status?')
    current = await running_context(settings, sessions, users['employee'], second)
    current.document_snapshot = 'visible-source-versions'
    return current, attachment, first, second, receipt


async def history(context):
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    return await conversation_history(context, job, [{'type': 'text', 'text': 'What was its status?'}])


async def test_followup_reuses_only_actual_delivered_fragments_and_registers_after_delivery(setup):
    context, attachment, first, second, receipt = await followup(setup)
    messages = await history(context)
    reference = next(m.content for m in messages if m.id == 'history:' + first['messageId'])
    assert first['messageId'] in reference
    assert 'feedbackProjection' not in reference and 'materialTranscript' not in reference
    source = next(m for m in messages if m.id == 'history-material:' + first['messageId'])
    assert isinstance(source, HumanMessage)
    wire = [{'role': 'user', 'content': source.content}]
    projected, supplied = project_document_messages(context, wire)
    evidence = json.loads(projected[0]['content'][0]['text'].split('已提供文档正文：')[1])
    assert evidence['items'][0]['text'] == receipt['items'][0]['text']
    assert evidence['readScope']['allExtractedTextReturned'] is False
    assert len(evidence['items']) == 1 and supplied == context.document_reads
    assert 'Unverified assistant' not in json.dumps(evidence)
    async with context.sessions() as db:
        job = await db.get(Job, second['jobId'])
        assert not job.result.get('documentTextProvided')
    await record_text_delivery(context, projected, supplied=supplied)
    async with context.sessions() as db:
        job = await db.get(Job, second['jobId'])
        assert set(job.result['documentTextProvided']) == set(supplied)
    # Rebuilding a resumed task does not change source text/input identities.
    assert next(m.content for m in await history(context) if m.id == source.id) == source.content


@pytest.mark.parametrize('change', ['not_delivered', 'revision', 'deleted_file', 'deleted_message', 'revoked', 'new_file', 'budget'])
async def test_unavailable_or_unprovided_prior_source_is_not_resurrected(setup, change):
    context, attachment, first, _, _ = await followup(setup, delivered=change != 'not_delivered')
    async with context.sessions.begin() as db:
        if change == 'revision':
            item = await db.get(Attachment, attachment['id']); item.extraction_revision += 1
        elif change == 'deleted_file':
            item = await db.get(Attachment, attachment['id']); item.deleted = True
        elif change == 'deleted_message':
            item = await db.get(Message, first['messageId']); item.deleted = True
        elif change == 'revoked':
            item = await db.get(Job, first['jobId']); item.access = {'role': 'admin', 'team': True}
    if change == 'new_file':
        context.current_document_ids = (attachment['id'],)
    if change == 'budget':
        context.model_binding = {'assistant': {'contextCapability': {'contextWindow': 4500}}}
    assert not any(m.id and m.id.startswith('history-material:') for m in await history(context))
    assert not context.document_reads


async def test_plain_history_has_no_document_query():
    from app.agent.context.document_history import previous_document_text
    class NoQuery:
        async def scalar(self, statement):
            raise AssertionError('Plain chat must not query previous attachment evidence')
    context = SimpleNamespace(document_snapshot='', context_sources={'previousMessageId': 'old'})
    assert await previous_document_text(NoQuery(), context, None, None, [{'id': 'old'}], '') is None


async def test_history_preserves_partial_conversion_and_visual_limits(setup):
    context, attachment, _, _, _ = await followup(setup)
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, attachment['id'])
        item.extraction_info = {**item.extraction_info, 'originalFormat': 'doc', 'convertedFormat': 'docx',
                                'hasVisuals': False, 'sourceComplete': False, 'warnings': ['部分文字未读取']}
    source = next(m for m in await history(context) if m.id and m.id.startswith('history-material:'))
    receipt = json.loads(source.content[0]['text'].split('已提供文档正文：')[1])
    extraction = receipt['attachment']['extraction']
    assert extraction['convertedFormat'] == 'docx' and extraction['originalFormat'] == 'doc'
    assert extraction['hasVisuals'] is None and extraction['conversionFidelityVerified'] is False
    assert extraction['visualDetectionBasis'] == 'converted_file'
    assert receipt['readScope']['sourceComplete'] is False
    assert receipt['readScope']['pageImagesIncluded'] is False
    assert receipt['readScope']['warnings'] == ['部分文字未读取']


async def test_over_budget_source_does_not_keep_only_its_early_fragments(setup):
    context, attachment, first, _, _ = await followup(setup)
    async with context.sessions.begin() as db:
        chunks = (await db.scalars(select(DocumentChunk).where(DocumentChunk.attachment_id == attachment['id']))).all()
        for chunk in chunks:
            chunk.text = 'x' * 5000
        origin = await db.get(Job, first['jobId'])
        origin.result = {**origin.result, 'documentTextProvided': {
            f'{attachment["id"]}:1:{c.ordinal}': [attachment['id'], 1, c.ordinal] for c in chunks}}
    assert not any(m.id and m.id.startswith('history-material:') for m in await history(context))
    assert not context.document_reads
