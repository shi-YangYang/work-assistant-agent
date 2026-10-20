"""Verified citation display never promotes unknown tokens or rewrites syntax."""
import json

import pytest
from fastapi import HTTPException

from _support.http.management import conversation, message
from _support.materials.documents import running_context, upload
from app.agent.tools.resources.documents import read_document_result
from app.modules.attachments.documents import normalize_citation_wrappers, verified_citations
from app.modules.attachments.models import Attachment
from app.tasks.models import Job
from app.tasks.processing.documents import prepare_document

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('text, expected', [
    ('事实〔[[file:valid]]〕。', '事实[[file:valid]]。'),
    ('事实〔〔 [[file:valid]] 〕〕。', '事实[[file:valid]]。'),
    ('事实〔[[page:valid]]〕。', '事实[[page:valid]]。'),
    ('普通（[[file:valid]]）和〔参见 [[file:valid]]〕', '普通（[[file:valid]]）和〔参见 [[file:valid]]〕'),
    ('〔[[file:unknown]]〕和〔[[file:stale]]〕', '〔[[file:unknown]]〕和〔[[file:stale]]〕'),
    ('〔〔[[file:valid]]〕', '〔〔[[file:valid]]〕'),
    ('`〔[[file:valid]]〕` 后的〔[[file:valid]]〕', '`〔[[file:valid]]〕` 后的[[file:valid]]'),
    ('``例子 `〔[[file:valid]]〕` ``', '``例子 `〔[[file:valid]]〕` ``'),
    ('```text\n〔[[file:valid]]〕\n```\n〔[[file:valid]]〕', '```text\n〔[[file:valid]]〕\n```\n[[file:valid]]'),
    ('~~~text\n〔[[file:valid]]〕\n~~~\n〔[[page:valid]]〕', '~~~text\n〔[[file:valid]]〕\n~~~\n[[page:valid]]'),
    ('```text\n〔[[file:valid]]〕', '```text\n〔[[file:valid]]〕'),
])
async def test_only_balanced_successful_citation_wrappers_are_normalized(text, expected):
    replacements = {'[[file:valid]]': '〔1〕', '[[page:valid]]': '〔2〕',
                    '[[file:unknown]]': '（来源未核实）', '[[file:stale]]': '（来源已变化）'}
    assert normalize_citation_wrappers(text, replacements) == expected


async def citation_source(setup):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    item = await upload(clients['employee'], 'citation.txt', b'real source')
    sent = await message(clients['employee'], conv, 'Read source', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    await prepare_document(context, item['id'])
    result = json.loads(await read_document_result(context, item['id']))
    async with sessions.begin() as db:
        attachment = await db.get(Attachment, item['id'])
        job = await db.get(Job, sent['jobId'])
        page = {'attachmentId': item['id'], 'revision': attachment.extraction_revision,
                'sha256': attachment.sha256, 'page': 1, 'location': '第 1 页',
                'resolution': 'normal', 'sheet': '', 'renderer': 'controlled'}
        job.result = {**job.result, 'documentPagesProvided': {
            'actual-page': page, 'stale-page': {**page, 'sha256': 'stale'},
        }}
    return context, item['id'], result['items'][0]['citation']


async def test_wrapped_file_and_page_citations_keep_numbering_and_exact_source_identity(setup):
    context, identifier, citation = await citation_source(setup)
    # Keep the existing file-before-page numbering even when the page is mentioned first.
    text = f'页图〔[[page:actual-page]]〕，文字〔{citation}〕，再引〔〔{citation}〕〕，普通（{citation}）。'
    async with context.sessions() as db:
        answer, refs = await verified_citations(db, context, text)
    assert answer == '页图〔2〕，文字〔1〕，再引〔1〕，普通（〔1〕）。'
    assert len(refs) == 2 and all(row['attachmentId'] == identifier for row in refs)
    assert refs[0]['ordinal'] == 0 and refs[1]['page'] == 1


async def test_unknown_and_stale_wrappers_keep_existing_rejection(setup):
    context, identifier, citation = await citation_source(setup)
    revision = context.document_reads[citation[len('[[file:'):-2]][1]
    stale = f'{identifier}:{revision}:999'
    context.document_reads[stale] = (identifier, revision, 999)
    text = f'〔{citation}〕 〔[[file:invented:1:0]]〕 〔[[file:{stale}]]〕 〔[[page:invented]]〕 〔[[page:stale-page]]〕'
    async with context.sessions() as db:
        answer, refs = await verified_citations(db, context, text)
    assert answer == '〔1〕 〔（来源未核实）〕 〔（来源已变化）〕 〔（页面未核实）〕 〔（来源已变化）〕'
    assert len(refs) == 1


async def test_wrapping_cannot_grant_access_to_another_users_attachment(setup):
    context, identifier, citation = await citation_source(setup)
    settings, sessions, users, clients = setup
    conv = await conversation(clients['peer'])
    sent = await message(clients['peer'], conv, 'Read another source')
    foreign = await running_context(settings, sessions, users['peer'], sent)
    foreign.document_reads = dict(context.document_reads)
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await verified_citations(db, foreign, f'〔{citation}〕')
    assert error.value.status_code == 404
