"""Read media retain authorization without misleading document coverage notes."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.base import uid
from app.agent.tools.business.work_records import read_work_material
from app.modules.attachments.documents import material_coverage, append_material_coverage, detach_material_coverage
from app.modules.attachments.models import Attachment
from app.tasks.lease import lease
from app.tasks.models import Job
from _support.agent.business_actions import runtime
from _support.work.work_records import create

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('kind', ['audio', 'image'])
async def test_successful_media_read_keeps_source_checks_and_only_documents_have_chunk_counts(setup, monkeypatch, kind):
    settings, sessions, users, clients = setup
    identifier = uid()
    data = b'controlled material source'
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / identifier).write_bytes(data)
    async with sessions.begin() as db:
        db.add(Attachment(id=identifier, company_id=users['employee'].company_id, owner_id=users['employee'].id,
                          kind=kind, name='材料.' + ('wav' if kind == 'audio' else 'png'), mime='audio/wav' if kind == 'audio' else 'image/png',
                          size=len(data), sha256=hashlib.sha256(data).hexdigest(), extraction_status='ready',
                          extraction_info={'transcript': '录音里的验收要求'} if kind == 'audio' else {}))
    work = await create(clients['employee'], materials=[{'attachmentId': identifier}])
    material = (await clients['employee'].get('/api/v1/work-items/' + work['id'] + '/materials')).json()['items'][0]
    context, _ = await runtime(setup, '读取工作中的材料')
    if kind == 'image':
        monkeypatch.setattr('app.integrations.media.image_process', AsyncMock(return_value={'tiles': [], 'complete': True}))
        monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', AsyncMock(return_value=AIMessage(content='受控图片读取结果')))
    result = json.loads(await read_work_material.coroutine(work['id'], material['id'], SimpleNamespace(context=context)))
    assert result['status'] == 'ready' and result['text']
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        sources = (await db.scalars(select(Attachment).where(Attachment.id.in_(context.document_versions)))).all()
        assert len(sources) == 1
        coverage, legacy = await material_coverage(db, users['employee'], job, sources, context.document_reads)
        assert append_material_coverage('已经读取材料。', coverage, legacy) == '已经读取材料。'
        document = Attachment(id=uid(), kind='document', name='需求.txt', extraction_status='ready',
                              extraction_revision=1, extraction_info={'chunks': 1}, sha256='a' * 64)
        coverage, legacy = await material_coverage(db, users['employee'], job, [*sources, document], {'read': [document.id, 1, 0]})
        assert coverage == ['需求.txt：工具已读取 1/1 段文字']
        assert append_material_coverage('已经读取材料。', coverage, legacy).endswith('\n\n本次材料范围：\n需求.txt：工具已读取 1/1 段文字')
    async with sessions.begin() as db:
        (await db.get(Attachment, material['attachment']['id'])).deleted = True
    async with sessions() as db:
        with pytest.raises(HTTPException):
            await lease(db, context)


def coverage_document(identifier='text', **changes):
    values = {'id': identifier, 'kind': 'document', 'name': identifier + '.txt', 'extraction_status': 'ready',
              'extraction_revision': 1, 'extraction_info': {'chunks': 2, 'schema': 1, 'sourceComplete': True}, 'sha256': 'a' * 64}
    values.update(changes)
    return SimpleNamespace(**values)


async def coverage_for(documents, reads=None, result=None, executions=()):
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: executions)))
    actor = SimpleNamespace(id='actor', company_id='company')
    job = SimpleNamespace(id='job', result=result or {})
    value = await material_coverage(db, actor, job, documents, reads or {})
    db.scalars.assert_awaited_once()
    return value


async def test_complete_delivered_text_is_grouped_without_counting_images_or_duplicate_reads():
    documents = [coverage_document(str(i)) for i in range(7)]
    reads = {f'{doc.id}-{ordinal}': [doc.id, 1, ordinal] for doc in documents for ordinal in range(2)}
    reads['duplicate'] = reads['0-0']
    image = SimpleNamespace(kind='image')
    coverage, legacy = await coverage_for([*documents, image], reads, {'documentPreloaded': list(reads), 'documentTextProvided': reads})
    assert coverage == ['7 份文件的已提取文字已全部提供给主模型']
    assert len(legacy) == len(coverage.previous) == 7
    assert '已准备文字 2/2 个分段；本任务已向主模型提供 2 个文字分段' in coverage.previous[0]


@pytest.mark.parametrize('status,info,reads,result,expected', [
    ('ready', {}, {'a': ['text', 1, 0], 'b': ['text', 1, 1]}, {'documentPreloaded': ['a', 'b']},
     '文字已准备（2/2 段），未记录是否提供给主模型'),
    ('ready', {}, {'a': ['text', 1, 0]}, {'documentPreloaded': ['a'], 'documentTextProvided': {}},
     '文字尚未提供给主模型'),
    ('ready', {}, {'a': ['text', 1, 0]}, {}, '工具已读取 1/2 段文字'),
    ('ready', {}, {}, {}, '尚未读取文字（共 2 段）'),
    ('ready', {}, {'a': ['text', 1, 0]}, {'documentTextProvided': {'a': ['text', 1, 0]}},
     '仅向主模型提供 1/2 段已提取文字，其余文字未提供'),
    ('partial', {}, {'a': ['text', 1, 0], 'b': ['text', 1, 1]}, {'documentTextProvided': {'a': ['text', 1, 0], 'b': ['text', 1, 1]}},
     '已提取文字已全部提供给主模型；文件文字仅部分可读'),
    ('failed', {'error': '文件损坏'}, {}, {'documentTextProvided': {}}, '文字提取失败：文件损坏'),
    ('ready', {'chunks': 0}, {}, {'documentTextProvided': {}}, '未提取到可读文字'),
    ('ready', {'sourceComplete': False}, {'a': ['text', 1, 0], 'b': ['text', 1, 1]}, {'documentTextProvided': {'a': ['text', 1, 0], 'b': ['text', 1, 1]}},
     '已提取文字已全部提供给主模型；原文件仍有未提取范围'),
    ('ready', {'hasVisuals': True}, {}, {}, '尚未读取文字（共 2 段）；图片部分未读取'),
    ('ready', {'hasVisuals': True, 'totalPages': 3}, {}, {'documentPagesProvided': {'page': {'attachmentId': 'text', 'revision': 1, 'page': 2, 'imageComplete': False}}},
     '尚未读取文字（共 2 段）；已向主模型提供第 2 页图片；所提供页面仍有图片区域未读取；其余页面图片未读取'),
    ('ready', {}, {'old': ['text', 0, 0]}, {'documentPreloaded': ['old'], 'documentTextProvided': {'old': ['text', 0, 0]}},
     '文字尚未提供给主模型'),
])
async def test_incomplete_or_unconfirmed_scope_stays_explicit(status, info, reads, result, expected):
    document = coverage_document(extraction_status=status)
    document.extraction_info.update(info)
    coverage, _ = await coverage_for([document], reads, result)
    assert coverage == ['text.txt：' + expected]


async def test_reused_text_keeps_delivery_and_revision_boundaries():
    document = coverage_document()
    reads = {'a': ['text', 1, 0], 'b': ['text', 1, 1], 'old': ['text', 0, 0]}
    result = {'documentReadAliases': {key: 'other' for key in reads}}
    coverage, _ = await coverage_for([document], reads, result)
    assert coverage == ['text.txt：工具已读取 2/2 段文字；含 2 段复用自相同内容附件']
    coverage, _ = await coverage_for([document], reads, {**result, 'documentTextProvided': reads})
    assert coverage == ['1 份文件的已提取文字已全部提供给主模型，其中 1 份复用了相同内容附件的文字']


@pytest.mark.parametrize('direct,revision,sha256,expected', [
    (True, 1, 'a' * 64, '原文件已提供给代码执行，具体读取范围未单独记录'),
    (False, 1, 'a' * 64, '仅关联代码执行，不能据此认定已读取原文件'),
    (True, 0, 'a' * 64, None),
    (True, 1, 'b' * 64, None),
])
async def test_code_input_and_related_source_are_not_promoted_to_model_text(direct, revision, sha256, expected):
    execution = SimpleNamespace(sources=[{'kind': 'attachment', 'id': 'text', 'revision': revision, 'sha256': sha256}],
                                result={'inputRefs': [{'attachment_id': 'text'}] if direct else []})
    coverage, _ = await coverage_for([coverage_document()], executions=[execution])
    assert coverage == ['text.txt：尚未读取文字（共 2 段）' + ('；' + expected if expected else '')]


@pytest.mark.parametrize('format_name', ['current', 'previous', 'legacy'])
@pytest.mark.parametrize('separator', ['', '\n'])
async def test_append_replaces_only_equivalent_terminal_notes_and_is_idempotent(format_name, separator):
    document = coverage_document()
    reads = {'a': ['text', 1, 0], 'b': ['text', 1, 1]}
    coverage, legacy = await coverage_for([document], reads, {'documentPreloaded': list(reads), 'documentTextProvided': reads})
    lines = {'current': coverage, 'previous': coverage.previous, 'legacy': legacy}[format_name]
    note = '\n\n材料范围：' + separator + '\n'.join(lines)
    original = '结论保持不变。\n\n材料范围：这是正文中的独立说明。\n\n后续建议仍需保留。'
    expected = original + '\n\n本次材料范围：\n' + '\n'.join(coverage)
    actual = append_material_coverage(original + note + note, coverage, legacy)
    assert actual == expected
    assert append_material_coverage(actual, coverage, legacy) == expected
    unrelated = original + '\n\n材料范围：\ntext.txt：仅提供一半，仍需检查。'
    assert append_material_coverage(unrelated, coverage, legacy).startswith(unrelated + '\n\n')


async def test_previous_scope_footer_is_not_presented_as_current_reading():
    old = '3 份文件的已提取文字已全部提供给主模型'
    previous = '三份文件合计为 250。\n\n材料范围：\n' + old
    prose, historical = detach_material_coverage(previous, {})
    assert prose == '三份文件合计为 250。' and historical == [old]
    coverage, legacy = await coverage_for([coverage_document()], result={'documentTextProvided': {}})
    updated = append_material_coverage(previous, coverage, legacy)
    assert old not in updated and '本次材料范围：' in updated
    assert '文字尚未提供给主模型' in updated
    prose, historical = detach_material_coverage(updated, {'materialCoverage': list(coverage)})
    assert prose == '三份文件合计为 250。' and historical == coverage
    ordinary = '材料范围：请同时比较第二份文件中的报价。'
    assert detach_material_coverage(ordinary, {}) == (ordinary, [])


@pytest.mark.parametrize('stored', [True, False])
async def test_material_scope_keeps_following_image_warning_and_answer_prose(stored):
    coverage = ['sample.txt：工具已读取 3/3 段文字']
    prose = '编号是 R7K9Q2。'
    following = '图片范围：\n照片.png：图片过大，仅提供缩略图\n\n下一步请核对报价。'
    note = '\n\n本次材料范围：\n' + '\n'.join(coverage)
    original = prose + note + '\n\n' + following
    assert detach_material_coverage(original, {'materialCoverage': coverage} if stored else {}) == (prose + '\n\n' + following, coverage)
    wrong = {'materialCoverage': ['sample.txt：工具已读取 2/3 段文字']}
    assert detach_material_coverage(original, wrong) == (original, [])
    appended = append_material_coverage(original, ['sample.txt：文字尚未提供给主模型'], [])
    assert appended == prose + '\n\n' + following + '\n\n本次材料范围：\nsample.txt：文字尚未提供给主模型'


async def test_converted_text_coverage_never_certifies_original_graphics_or_layout():
    document = coverage_document()
    document.extraction_info.update(originalFormat='doc', convertedFormat='docx', hasVisuals=False)
    reads = {'a': ['text', 1, 0], 'b': ['text', 1, 1]}
    coverage, _ = await coverage_for([document], reads, {'documentTextProvided': reads})
    assert coverage == ['text.txt：已提取文字已全部提供给主模型；转换后内容，原件图形及版式是否完整未核验']
