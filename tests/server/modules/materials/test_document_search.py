"""Bounded content search advances sources without broadening delivered evidence."""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from _support.http.management import conversation, message
from _support.materials.documents import upload, running_context
from app.agent.tools.resources.documents import read_document_result
from app.modules.attachments.models import Attachment, DocumentChunk
from app.tasks.context import InputChanged, LostLease
from app.tasks.models import Job
from app.tasks.processing.documents import prepare_document
from app.tasks.processing.document_ranges import ensure_range

pytestmark = pytest.mark.asyncio


async def source(setup, content):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    item = await upload(clients['employee'], 'search.txt', content.encode())
    sent = await message(clients['employee'], conv, 'Find the requested value', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    await prepare_document(context, item['id'])
    return context, item['id']


async def test_query_work_bound_gaps_and_resume_never_claim_unreturned_text_read(setup):
    content = '\n'.join('x' * 110 for _ in range(24000)) + '\nFINAL-FACT'
    context, identifier = await source(setup, content)
    first = json.loads(await read_document_result(context, identifier, limit=1))
    assert first['nextCursor'] == 1 and not first['sourceComplete']
    await ensure_range(context, identifier, 300)
    result = json.loads(await read_document_result(context, identifier, query='FINAL-FACT', limit=3))
    assert not result['items'] and result['nextCursor'] > 0
    assert result['searchScope']['stopReason'] == 'batch_limit'
    assert result['searchScope']['batches'] == 3
    assert len(context.document_reads) == 1
    ranges = result['searchScope']['ranges']
    assert ranges[0][0] == 0 and all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
    cursor = result['nextCursor']
    # A changed query still starts where explicitly requested, never skips a gap.
    resumed = json.loads(await read_document_result(context, identifier, start=cursor, query='not present', limit=3))
    assert resumed['searchScope']['fromOrdinal'] == cursor
    assert resumed['searchScope']['ranges'][0][0] == cursor
    assert len(context.document_reads) == 1


async def test_prepared_query_pages_bound_scan_and_match_pagination(setup):
    context, identifier = await source(setup, 'initial')
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        original = await db.scalar(select(DocumentChunk).where(DocumentChunk.attachment_id == identifier))
        original.text = 'row 0'
        for index in range(1, 2105):
            db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=identifier,
                                 revision=item.extraction_revision, ordinal=index, location=f'行 {index + 1}',
                                 text='TARGET' if index >= 2100 else f'row {index}'))
        item.extraction_info = {**item.extraction_info, 'chunks': 2105, 'sourceEnd': 2105,
                                'extractedRanges': [[0, 2105]], 'sourceComplete': True, 'nextExtractCursor': None}
    result = json.loads(await read_document_result(context, identifier, query='TARGET', limit=3))
    assert [row['ordinal'] for row in result['items']] == [2100, 2101, 2102]
    assert result['nextCursor'] == 2103
    assert result['searchScope']['ranges'] == [[0, 2000], [2000, 2105]]
    assert [row['ordinal'] for row in result['contextItems']] == [2099, 2103, 2104]
    assert len(context.document_reads) == 6
    following = json.loads(await read_document_result(context, identifier, start=2103, query='TARGET', limit=3))
    assert [row['ordinal'] for row in following['items']] == [2103, 2104]
    assert following['nextCursor'] is None and following['searchScope']['toOrdinal'] == 2105
    assert len(context.document_reads) == 6


async def test_search_returns_late_match_and_nearby_facts_without_skipping_middle_matches(setup):
    context, identifier = await source(setup, 'initial')
    texts = ['initial', '修订说明见后续条款', 'background', '修订规则与流程', 'background',
             '修订须经双方确认', 'background', '修订后的维护要求', 'middle fact',
             '修订备忘录', '最终交货日期：2031-04-30', '数量：72台', 'irrelevant']
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        for index, value in enumerate(texts[1:], 1):
            db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=identifier,
                                 revision=item.extraction_revision, ordinal=index, location=f'段落 {index + 1}', text=value))
        item.extraction_info = {**item.extraction_info, 'chunks': len(texts), 'sourceEnd': len(texts),
                                'extractedRanges': [[0, len(texts)]], 'sourceComplete': True}
    result = json.loads(await read_document_result(context, identifier, query='修订', limit=3))
    assert [row['ordinal'] for row in result['items']] == [1, 3, 5]
    assert result['nextCursor'] == 6
    assert any(row['text'] == '最终交货日期：2031-04-30' for row in result['contextItems'])
    assert result['searchScope']['matchedOrdinals'] == [1, 3, 5, 7, 9]
    actual = [*result['items'], *result['contextItems']]
    assert sum(len(row['text']) for row in actual) <= 12000
    assert {entry[2] for entry in context.document_reads.values()} == {row['ordinal'] for row in actual}
    # Returned neighbour/last-match context does not consume the middle page.
    resumed = json.loads(await read_document_result(context, identifier, start=6, query='修订', limit=3))
    assert [row['ordinal'] for row in resumed['items']] == [7, 9]


@pytest.mark.parametrize(('query', 'mode', 'expected'), [
    ('价格 交期', 'any_term', [1, 2, 3]), ('"价格 交期"', 'phrase', []),
    ('价格 金额', 'phrase', [3]), ('%', 'phrase', [4]),
])
async def test_query_exact_phrase_and_quoted_literals_precede_bounded_terms(setup, query, mode, expected):
    context, identifier = await source(setup, 'initial')
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        for index, value in enumerate(['价格为72元', '交期为四月', '价格 金额说明', '折扣5%'], 1):
            db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=identifier,
                                 revision=item.extraction_revision, ordinal=index, location=f'段落 {index}', text=value))
        item.extraction_info = {**item.extraction_info, 'chunks': 5, 'sourceEnd': 5, 'extractedRanges': [[0, 5]], 'sourceComplete': True}
    result = json.loads(await read_document_result(context, identifier, query=query, limit=3))
    assert result['searchScope']['searchMode'] == mode
    assert [row['ordinal'] for row in result['items']] == expected


async def test_legacy_search_and_return_budget_do_not_skip_a_missing_match(setup):
    from app.modules.attachments.documents import chunk_page
    context, identifier = await source(setup, 'initial')
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        item.extraction_info = {'chunks': 4, 'sourceComplete': True}
        for index, text in enumerate(['TARGET ' + 'x' * 8500, 'TARGET ' + 'y' * 5000, 'TARGET short'], 1):
            db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=identifier,
                                 revision=item.extraction_revision, ordinal=index, location=f'段落 {index}', text=text))
        await db.flush()
        result = await chunk_page(db, item, query='TARGET', limit=3)
        assert [row['ordinal'] for row in result['items']] == [1, 3]
        assert result['nextCursor'] == 2  # Oversized combined primary page cannot skip ordinal 2.
        assert sum(len(row['text']) for row in [*result['items'], *result['contextItems']]) <= 12000
        following = await chunk_page(db, item, start=2, query='TARGET', limit=3)
        assert [row['ordinal'] for row in following['items']] == [2, 3]
        assert following['nextCursor'] is None


@pytest.mark.parametrize('failure', ['parse', 'no-progress'])
async def test_failed_or_stalled_continuation_keeps_prior_evidence_and_stops(setup, monkeypatch, failure):
    context, identifier = await source(setup, 'x' * 500000)
    first = json.loads(await read_document_result(context, identifier, limit=1))
    reads = dict(context.document_reads)
    from app.tasks.processing import document_ranges
    if failure == 'parse':
        parser = AsyncMock(return_value={'status': 'failed', 'chunks': [], 'info': {'error': 'controlled range error'}})
        monkeypatch.setattr(document_ranges, 'parse_process', parser)
    else:
        monkeypatch.setattr(document_ranges, 'ensure_range', AsyncMock(return_value={}))
    result = json.loads(await read_document_result(context, identifier, query='absent', limit=3))
    assert result['searchScope']['stopReason'] == ('range_error' if failure == 'parse' else 'no_progress')
    assert result['nextCursor'] is None and result['scopeWarning'] and result['retryCursor'] > 0
    assert not result['items'] and context.document_reads == reads
    assert result['searchScope']['ranges'] == [[0, result['retryCursor']]]
    if failure == 'parse':
        assert parser.await_count == 1
    assert first['items'][0]['citation']


@pytest.mark.parametrize('change', ['cancel', 'version', 'deleted'])
async def test_continuation_revalidates_lease_version_and_attachment(setup, monkeypatch, change):
    context, identifier = await source(setup, 'x' * 500000)
    from app.tasks.processing import document_ranges
    async def interrupt(*args, **kwargs):
        async with context.sessions.begin() as db:
            if change == 'cancel':
                job = await db.get(Job, context.job_id)
                job.state = 'cancelled'
            else:
                item = await db.get(Attachment, identifier)
                if change == 'version':
                    item.extraction_revision += 1
                else:
                    item.deleted = True
        return {'status': 'failed', 'chunks': [], 'info': {'error': 'must not be returned as a parse failure'}}
    parser = AsyncMock(side_effect=interrupt)
    monkeypatch.setattr(document_ranges, 'parse_process', parser)
    error = LostLease if change == 'cancel' else InputChanged if change == 'version' else HTTPException
    with pytest.raises(error):
        await read_document_result(context, identifier, query='absent', limit=3)
    assert parser.await_count == 1 and not context.document_reads


async def test_foreign_query_cannot_trigger_source_preparation(setup, monkeypatch):
    context, identifier = await source(setup, 'private original')
    settings, sessions, users, clients = setup
    conv = await conversation(clients['peer'])
    sent = await message(clients['peer'], conv, 'Find text')
    foreign = await running_context(settings, sessions, users['peer'], sent)
    preparer = AsyncMock(side_effect=AssertionError('Unauthorized file must not be prepared'))
    monkeypatch.setattr('app.tasks.processing.document_ranges.ensure_range', preparer)
    result = json.loads(await read_document_result(foreign, identifier, query='private'))
    assert result['error'] == 'document_reference_unavailable'
    assert 'private original' not in str(result)
    preparer.assert_not_called()


@pytest.mark.parametrize('start_at_match', [False, True])
async def test_spreadsheet_match_returns_its_row_and_first_row_not_previous_record(setup, start_at_match):
    from io import BytesIO
    from openpyxl import Workbook
    settings, sessions, users, clients = setup
    book = Workbook(); sheet = book.active; sheet.title = '订单'
    sheet.append(['编号', '品名', '数量', '状态'])
    sheet.append(['OLD', '其它货物', 9, '已取消'])
    sheet.append(['TARGET', '标签纸', 12, '待发货'])
    other = book.create_sheet('另一张表')
    other.append(['编号', '状态']); other.append(['different', '已经签收'])
    data = BytesIO(); book.save(data)
    attachment = await upload(clients['employee'], 'orders.xlsx', data.getvalue())
    sent = await message(clients['employee'], await conversation(clients['employee']), 'Find target', [attachment['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    await prepare_document(context, attachment['id'])
    result = json.loads(await read_document_result(context, attachment['id'], start=8 if start_at_match else 0, query='TARGET', limit=3))
    rows = [*result['items'], *result['contextItems']]
    assert {row['location'] for row in rows} == {f'工作表「订单」!{column}{number}' for number in (1, 3) for column in 'ABCD'}
    assert any(row['text'] == 'D3：待发货' for row in rows)
    assert all('已取消' not in row['text'] and '已经签收' not in row['text'] for row in rows)
    assert result['searchScope']['contextMode'] == 'same_table_row_and_first_row'
    assert result['searchScope']['contextTruncated'] is False
    assert {value[2] for value in context.document_reads.values()} == {row['ordinal'] for row in rows}
    assert result['nextCursor'] is None


async def test_csv_record_match_never_mixes_neighbouring_record_status(setup):
    settings, sessions, users, clients = setup
    attachment = await upload(clients['employee'], 'orders.csv', b'id,item,status\nOLD,other,cancelled\nTARGET,label,pending\n')
    sent = await message(clients['employee'], await conversation(clients['employee']), 'Find target', [attachment['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    await prepare_document(context, attachment['id'])
    result = json.loads(await read_document_result(context, attachment['id'], query='TARGET', limit=3))
    assert [row['ordinal'] for row in result['items']] == [2]
    assert [row['ordinal'] for row in result['contextItems']] == [0]
    assert 'cancelled' not in str(result['items'] + result['contextItems'])
