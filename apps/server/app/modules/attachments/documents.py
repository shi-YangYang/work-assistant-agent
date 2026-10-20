import re
from app.core.errors import problem
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkRevision
from app.security.ownership import owned
from pathlib import Path
from sqlalchemy import select

DOCUMENT_TYPES = {
    '.doc': 'application/msword', '.xls': 'application/vnd.ms-excel',
    '.ppt': 'application/vnd.ms-powerpoint', '.rtf': 'application/rtf',
    '.odt': 'application/vnd.oasis.opendocument.text',
    '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
    '.odp': 'application/vnd.oasis.opendocument.presentation',
    '.pdf': 'application/pdf',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain', '.json': 'application/json', '.md': 'text/markdown', '.csv': 'text/csv',
}


def safe_name(name):
    basename = re.sub(r'[\x00-\x1f\x7f]', '', (name or 'attachment').replace('\\', '/').split('/')[-1]) or 'attachment'
    suffix = Path(basename).suffix[:16]
    return basename if len(basename) <= 180 else basename[:180 - len(suffix)] + suffix


def document_type(name, supplied_mime):
    from app.modules.attachments.policy import attachment_kind
    kind = attachment_kind(name)
    suffix = Path(name).suffix.lower()
    if suffix in DOCUMENT_TYPES:
        permitted = {DOCUMENT_TYPES[suffix], 'application/octet-stream', '', 'application/zip' if suffix in ('.docx', '.pptx', '.xlsx') else 'text/plain'}
        if suffix == '.rtf':
            permitted.add('text/rtf')
        if suffix in ('.odt', '.ods', '.odp', '.doc'):
            permitted.add('application/zip')
        if suffix in ('.json', '.csv', '.md'):
            permitted |= {'text/json', 'application/csv', 'application/vnd.ms-excel', 'text/x-markdown'}
        if (supplied_mime or '').split(';')[0].lower() not in permitted:
            problem(415, '文件类型与扩展名不一致，请重新导出后上传')
        return DOCUMENT_TYPES[suffix]
    return 'text/plain' if kind == 'document' else None


def attachment_dto(a):
    return {'id': a.id, 'kind': a.kind, 'name': a.name, 'size': a.size, 'mime': a.mime, 'duration': a.duration, 'url': f'/api/v1/uploads/{a.id}/content', 'previewUrl': f'/api/v1/uploads/{a.id}/preview' if a.kind in ('image', 'audio') else None, 'image': a.extraction_info if a.kind == 'image' else None, 'extraction': {'status': a.extraction_status, 'revision': a.extraction_revision, 'parserVersion': a.parser_version, **{key: value for key, value in (a.extraction_info or {}).items() if key in ('error', 'warnings', 'scope', 'characters', 'chunks', 'stage', 'originalFormat', 'convertedFormat', 'schema', 'sourceComplete', 'nextExtractCursor', 'sourceEnd', 'extractedRanges', 'hasVisuals', 'totalPages', 'visualPages', 'visualError', 'rangeError')}} if a.kind == 'document' else None}


def document_reference(item):
    """Agent-facing discovery metadata; extraction is not a reading receipt."""
    return prepared_document_reference(attachment_dto(item), message_id=item.message_id)


def prepared_document_reference(dto, *, message_id=None):
    """Project prepared DTOs without another query or changing the public DTO."""
    value = {key: dto[key] for key in ('id', 'kind', 'name')}
    info = dto['extraction'] or {}
    value['extraction'] = dict(info)
    if info.get('scope') == '已提取文字；页面图片通过视觉读取补充，隐藏区域不纳入范围':
        value['extraction']['scope'] = '已提取文字'
    if message_id:
        value['messageId'] = message_id
    if info.get('convertedFormat'):
        # A negative detector result describes the converted file only. It
        # cannot rule out visual objects lost while converting the original.
        value['extraction'] = {**value['extraction'],
                               'hasVisuals': True if info.get('hasVisuals') else None,
                               'visualDetectionBasis': 'converted_file',
                               'conversionFidelityVerified': False}
    value['readText'] = {'tool': 'read_document', 'attachment_id': dto['id'], 'start': 0}
    if info.get('hasVisuals') or info.get('convertedFormat') or Path(dto['name']).suffix.lower() == '.pdf':
        value['readPages'] = {'tool': 'read_document', 'attachment_id': dto['id'], 'start': 0, 'view': 'pages', 'pages': [1]}
        if Path(dto['name']).suffix.lower() in ('.xls', '.xlsx', '.ods'):
            value['readPages']['sheetRequired'] = True
    return value


def table_structure_reference(info):
    """Clarify existing statistics without mutating or reparsing stored output."""
    if not (structure := info.get('tableStructure')):
        return None
    sheets = []
    for source in structure.get('sheets', []):
        row = {key: value for key, value in source.items()
               if key not in ('hiddenRowsExcluded', 'hiddenColumnsExcluded')}
        hidden_rows = source.get('hiddenRowsExcluded')
        hidden_columns = source.get('hiddenColumnsExcluded')
        row['hiddenRowsPresent'] = hidden_rows if type(hidden_rows) is bool else None
        row['hiddenColumnsPresent'] = hidden_columns if type(hidden_columns) is bool else None
        row['hiddenContentStatus'] = ('not_read' if hidden_rows is True or hidden_columns is True else
                                      'not_present' if hidden_rows is False and hidden_columns is False else 'unknown')
        sheets.append(row)
    return {**structure, 'sheets': sheets,
            'basis': '完整遍历可见单元格值或公式；无值行数仅计首末内容行之间。合并表不判空行，格式不算内容。'}


async def visible_attachment(db, identifier, actor, *, lock=False, work_revision=None):
    item = await owned(db, Attachment, identifier, actor, read=True, lock=lock)
    if not item.message_id:
        from app.modules.work.materials.queries import work_for_material
        if await work_for_material(db, actor, item.id, work_revision=work_revision):
            return item
        if item.owner_id != actor.id:
            problem(404, '附件尚未发送或无权查看')
    else:
        from app.modules.operations.mutations.publication import shared_attachment, published_attachment
        if item.owner_id == actor.id and await published_attachment(db, item):
            return item
        if item.owner_id != actor.id and await shared_attachment(db, actor, item):
            return item
        message = await owned(db, Message, item.message_id, actor, read=True)
        if message.owner_id != item.owner_id:
            problem(404, '附件来源不可用')
    return item


async def document_statement(db, actor, job):
    current = await owned(db, Message, job.target_id, actor) if job.kind == 'message' else None
    revisions = (await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkItem.deleted.is_(False), WorkRevision.owner_id == actor.id, WorkRevision.company_id == actor.company_id, *([WorkRevision.id.in_(job.result.get('sourceIds', []))] if job.kind == 'report' else [])))).all()
    sources = {mid for revision in revisions for mid in revision.source_ids}
    published = {aid for revision in revisions for aid in revision.publication.get('attachmentIds', [])}
    scope = Message.id.in_(sources)
    if current:
        scope = scope | (Message.conversation_id == current.conversation_id)
    from app.modules.work.models import WorkMaterial
    material_files = select(WorkMaterial.attachment_id).join(WorkItem, WorkItem.id == WorkMaterial.work_id).where(WorkMaterial.owner_id == actor.id, WorkMaterial.company_id == actor.company_id, WorkMaterial.removed.is_(False), WorkItem.deleted.is_(False))
    return select(Attachment).outerjoin(Message, Message.id == Attachment.message_id).where(Attachment.owner_id == actor.id, Attachment.company_id == actor.company_id, Attachment.deleted.is_(False), Attachment.kind == 'document', (Message.deleted.is_(False) & scope) | Attachment.id.in_(published) | Attachment.id.in_(material_files))


async def agent_attachment(db, identifier, actor, job):
    # Admin team browsing never grants the assistant cross-employee access.
    item = await owned(db, Attachment, identifier, actor)
    from app.modules.work.materials.queries import work_for_material
    if work := await work_for_material(db, actor, item.id):
        from app.modules.work.materials.queries import require_agent_work
        await require_agent_work(db, actor, job, work)
        return item
    if item.kind != 'document' or not item.message_id:
        problem(404, '文件不可用或尚未发送')
    from app.modules.operations.mutations.publication import published_attachment
    if await published_attachment(db, item, revision_ids=job.result.get('sourceIds', []) if job.kind == 'report' else None):
        return item
    message = await owned(db, Message, item.message_id, actor)
    current = await owned(db, Message, job.target_id, actor) if job.kind == 'message' else None
    if not current or message.conversation_id != current.conversation_id:
        source = await db.scalar(select(WorkRevision.id).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == actor.id, WorkItem.deleted.is_(False), WorkRevision.source_ids.contains([message.id])).limit(1))
        if source is None:
            problem(404, '文件不属于当前会话或本人已确认工作来源')
        if job.kind == 'report':
            bound = await db.scalar(select(WorkRevision.id).where(WorkRevision.id.in_(job.result.get('sourceIds', [])), WorkRevision.owner_id == actor.id, WorkRevision.company_id == actor.company_id, WorkRevision.source_ids.contains([message.id])).limit(1))
            if bound is None:
                problem(404, '文件不属于本次报告的已确认来源')
    return item


PAGE_CHARACTERS = 12000
PAGE_CHUNKS = 40
SEARCH_CHUNKS = 2000


def table_row_location(location):
    """Recognize parser positions, without inferring headers or cell contents."""
    match = re.fullmatch(r'工作表「(.*)」!([A-Z]+)([1-9]\d*)(?::[A-Z]+([1-9]\d*))?(?: · (?:该范围内)?字符 \d+–\d+)?', location)
    if match and (match[4] is None or match[4] == match[3]):
        return ('sheet', match[1], int(match[3]))
    match = re.fullmatch(r'记录 ([1-9]\d*) · 至行 \d+(?: · (?:该范围内)?字符 \d+–\d+)?', location)
    if match:
        return ('record', '', int(match[1]))
    return None


async def search_chunks(db, item, start, end, limit, query):
    """Return ordered matches plus bounded context without moving the cursor past gaps."""
    from sqlalchemy import or_
    phrase = query[:120].strip()
    quoted = len(phrase) >= 2 and phrase[0] == phrase[-1] and phrase[0] in ('"', "'")
    if quoted:
        phrase = phrase[1:-1]
    base = select(DocumentChunk.ordinal).where(
        DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision,
        DocumentChunk.ordinal >= start, DocumentChunk.ordinal < end)
    matches = list((await db.scalars(base.where(DocumentChunk.text.icontains(phrase, autoescape=True))
                                    .order_by(DocumentChunk.ordinal))).all()) if phrase else []
    mode, terms = 'phrase', [phrase]
    if not matches and not quoted and len(parts := phrase.split()) > 1:
        terms, mode = list(dict.fromkeys(parts))[:8], 'any_term'
        matches = list((await db.scalars(base.where(or_(*(DocumentChunk.text.icontains(term, autoescape=True) for term in terms)))
                                        .order_by(DocumentChunk.ordinal))).all())
    primary = matches[:limit]
    # A later occurrence often qualifies an earlier mention. Include its actual
    # surrounding text, while nextCursor still preserves every middle match.
    anchors = list(dict.fromkeys([*primary, *matches[-limit:]]))
    neighbours = {ordinal for anchor in anchors for ordinal in range(max(start, anchor - 1), min(end, anchor + 3))}
    context_mode = None
    # Spreadsheet fragments are cells, not paragraphs. A preceding ordinal can
    # belong to another order; retain the matching physical row instead. Read
    # only bounded position metadata, never reparse or cross an extraction gap.
    tabular = Path(item.name).suffix.lower() in ('.xlsx', '.xls', '.ods', '.csv')
    positions = (await db.execute(select(DocumentChunk.ordinal, DocumentChunk.location).where(
        DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision,
        DocumentChunk.ordinal.in_(anchors)))).all() if anchors and tabular else []
    keyed = {ordinal: table_row_location(location) for ordinal, location in positions}
    targets = {keyed[anchor] for anchor in anchors if keyed.get(anchor)}
    context_positions_truncated = False
    if targets:
        context_mode = 'same_table_row_and_first_row'
        table_anchors = {anchor for anchor in anchors if keyed.get(anchor)}
        neighbours = {ordinal for anchor in anchors if anchor not in table_anchors
                      for ordinal in range(max(start, anchor - 1), min(end, anchor + 3))}
        first_rows = {(kind, sheet, 1) for kind, sheet, _ in targets}
        row_patterns = ['^' + (re.escape(f'工作表「{sheet}」!') + f'[A-Z]+{number}(?::[A-Z]+{number})?(?: · |$)'
                               if kind == 'sheet' else f'记录 {number} · 至行 ') for kind, sheet, number in targets | first_rows]
        contextual = (await db.execute(select(DocumentChunk.ordinal, DocumentChunk.location).where(
            DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision,
            or_(*(DocumentChunk.location.op('~')(pattern) for pattern in row_patterns)))
            .order_by(DocumentChunk.ordinal).limit(SEARCH_CHUNKS + 1))).all()
        context_positions_truncated = len(contextual) > SEARCH_CHUNKS
        keyed.update({ordinal: table_row_location(location) for ordinal, location in contextual[:SEARCH_CHUNKS]})
        neighbours.update(ordinal for ordinal, key in keyed.items() if key in targets | first_rows)
    rows = (await db.scalars(select(DocumentChunk).where(
        DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision,
        DocumentChunk.ordinal.in_(neighbours)).order_by(DocumentChunk.ordinal))).all() if neighbours else []
    by_id, selected, characters = {row.ordinal: row for row in rows}, {}, 0
    for ordinal in [*anchors, *sorted(neighbours - set(anchors))]:
        if (row := by_id.get(ordinal)) is not None and characters + len(row.text) <= PAGE_CHARACTERS:
            selected[ordinal] = row
            characters += len(row.text)
    main = [selected[ordinal] for ordinal in primary if ordinal in selected]
    extra = [selected[ordinal] for ordinal in sorted(selected.keys() - {row.ordinal for row in main})]
    # A skipped over-budget match remains resumable; neighbours are not matches.
    missing = next((ordinal for ordinal in primary if ordinal not in selected), None)
    following = missing if missing is not None else primary[-1] + 1 if primary and len(matches) > len(primary) else None
    returned_matches = sorted(set(matches) & selected.keys())
    return main, extra, following, {'searchMode': mode, 'terms': terms, 'matchedOrdinals': returned_matches,
                                    **({'contextMode': context_mode, 'contextTruncated': context_positions_truncated or bool(neighbours - selected.keys())} if context_mode else {}),
                                    'matchesInRange': len(matches), 'unreturnedMatchesInRange': len(matches) - len(returned_matches),
                                    **({'oversizedMatchOrdinals': [ordinal for ordinal in primary if len(by_id[ordinal].text) > PAGE_CHARACTERS]} if missing is not None else {})}


async def chunk_page(db, item, start=0, limit=PAGE_CHUNKS, query=''):
    info = item.extraction_info or {}
    intervals = info.get('extractedRanges', [])
    end = next((hi for lo, hi in intervals if lo <= start < hi), start)
    if query and info.get('schema') == 1:
        end = min(end, start + SEARCH_CHUNKS)
    legacy_end = None
    if query and info.get('schema') != 1:
        from sqlalchemy import func
        last = await db.scalar(select(func.max(DocumentChunk.ordinal)).where(
            DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision))
        legacy_end = last + 1 if last is not None else 0
        end = min(start + SEARCH_CHUNKS, legacy_end)
    statement = select(DocumentChunk).where(DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision, DocumentChunk.ordinal >= start)
    if info.get('schema') == 1:
        statement = statement.where(DocumentChunk.ordinal < end)
    context, search = [], {}
    if query:
        page, context, following, search = await search_chunks(db, item, start, end, limit, query)
    else:
        rows = list((await db.scalars(statement.order_by(DocumentChunk.ordinal).limit(limit + 1))).all())
        page, characters = [], 0
        for row in rows[:limit]:
            if page and characters + len(row.text) > PAGE_CHARACTERS:
                break
            page.append(row)
            characters += len(row.text)
        following = page[-1].ordinal + 1 if page and len(rows) > len(page) else None
    if following is None and info.get('schema') == 1 and (not info.get('sourceComplete') or query and end < info.get('sourceEnd', end)):
        following = max(start, end)
        if info.get('sourceEnd') is not None and following >= info['sourceEnd']:
            following = None
    if following is None and legacy_end is not None and end < legacy_end:
        following = end
    return {'attachment': attachment_dto(item), 'items': [{'ordinal': row.ordinal, 'location': row.location, 'text': row.text} for row in page],
            **({'contextItems': [{'ordinal': row.ordinal, 'location': row.location, 'text': row.text} for row in context]} if query else {}),
            'nextCursor': following, 'nextExtractCursor': info.get('nextExtractCursor'), 'sourceComplete': info.get('sourceComplete', False),
            'searchScope': {'fromOrdinal': start, 'toOrdinal': end,
                            'sourceEnd': info.get('sourceEnd'), **search} if query else None}


CITATION = re.compile(r'\[\[file:([^\]\n]+)\]\]')
_FOOTNOTE_WRAPPER = re.compile(r'(?P<open>〔+)[ \t]*(?P<key>\[\[(?:file|page):[^\]\n]+\]\])[ \t]*(?P<close>〕+)')
_CODE_SAMPLE = re.compile(
    r'(?m)^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^ {0,3}(?P=fence)[ \t]*(?:\n|$)|\Z)'
    r'|(?<!`)(?P<ticks>`+)(?!`)[\s\S]*?(?<!`)(?P=ticks)(?!`)')


def normalize_citation_wrappers(answer, replacements):
    """Strip only matched footnote wrappers around successfully verified tokens.

    Code samples retain the existing token replacement behavior; this display
    repair must not additionally rewrite their surrounding literal syntax.
    """
    if '〔' not in answer or not any(value.startswith('〔') for value in replacements.values()):
        return answer
    def unwrap(match):
        key = match['key']
        if (replacements.get(key, '').startswith('〔')
                and len(match['open']) == len(match['close'])):
            return key
        return match[0]
    parts, start = [], 0
    for code in _CODE_SAMPLE.finditer(answer):
        parts.extend((_FOOTNOTE_WRAPPER.sub(unwrap, answer[start:code.start()]), code[0]))
        start = code.end()
    parts.append(_FOOTNOTE_WRAPPER.sub(unwrap, answer[start:]))
    return ''.join(parts)


def document_chunk_location(location):
    """Character offsets restart within the preceding source location."""
    return re.sub(r' · 字符 (?=\d+–\d+$)', ' · 该范围内字符 ', location)


async def verified_citations(db, context, answer):
    from app.tasks.lease import lease
    job, actor = await lease(db, context)
    citations, replacements = [], {}
    for token in CITATION.findall(answer):
        key = '[[file:' + token + ']]'
        if key in replacements:
            continue
        evidence = context.document_reads.get(token)
        if evidence is None:
            replacements[key] = '（来源未核实）'
            continue
        aid, revision, ordinal = evidence
        item = await agent_attachment(db, aid, actor, job)
        chunk = await db.scalar(select(DocumentChunk).where(DocumentChunk.attachment_id == aid, DocumentChunk.revision == revision, DocumentChunk.ordinal == ordinal))
        if item.extraction_revision != revision or chunk is None:
            replacements[key] = '（来源已变化）'
            continue
        citations.append({'attachmentId': aid, 'revision': revision, 'ordinal': ordinal, 'name': item.name, 'location': document_chunk_location(chunk.location)})
        replacements[key] = f'〔{len(citations)}〕'
    from urllib.parse import urlencode
    for token in re.findall(r'\[\[page:([^\]\n]+)\]\]', answer):
        key = '[[page:' + token + ']]'
        if key in replacements:
            continue
        ref = job.result.get('documentPagesProvided', {}).get(token)
        if not ref:
            replacements[key] = '（页面未核实）'
            continue
        item = await agent_attachment(db, ref['attachmentId'], actor, job)
        if item.extraction_revision != ref['revision'] or item.sha256 != ref['sha256']:
            replacements[key] = '（来源已变化）'
            continue
        url = f'/api/v1/uploads/{item.id}/pages/{ref["page"]}?' + urlencode({'revision': ref['revision'], 'resolution': ref['resolution'], 'sheet': ref['sheet'], 'renderer': ref['renderer']})
        citations.append({'attachmentId': item.id, 'revision': ref['revision'], 'ordinal': -ref['page'], 'page': ref['page'], 'name': item.name, 'location': ref['location'], 'previewUrl': url})
        replacements[key] = f'〔{len(citations)}〕'
    answer = normalize_citation_wrappers(answer, replacements)
    for key, value in replacements.items():
        answer = answer.replace(key, value)
    return answer, citations


async def delivered_citations(db, context, answer):
    """One file card per delivered source; prose markers are optional legacy input."""
    from app.tasks.lease import lease
    from sqlalchemy import tuple_
    from urllib.parse import urlencode
    job, actor = await lease(db, context)
    text = job.result.get('documentTextProvided', {})
    pages = job.result.get('documentPagesProvided', {})
    tables = job.result.get('documentTableProvided', {})
    # Authorization is still the normal per-file check, never per text chunk.
    items = {}
    for identifier in dict.fromkeys([entry[0] for entry in text.values()] + [ref['attachmentId'] for ref in pages.values()] + [ref['attachmentId'] for ref in tables.values()]):
        items[identifier] = await agent_attachment(db, identifier, actor, job)
    identities = {tuple(entry) for entry in text.values() if items[entry[0]].extraction_revision == entry[1]}
    chunks = {}
    if identities:
        rows = (await db.execute(select(DocumentChunk.attachment_id, DocumentChunk.revision, DocumentChunk.ordinal, DocumentChunk.location).where(
            tuple_(DocumentChunk.attachment_id, DocumentChunk.revision, DocumentChunk.ordinal).in_(identities)))).all()
        chunks = {(row.attachment_id, row.revision, row.ordinal): row for row in rows}
    citations, positions, replacements = [], {}, {}
    def register(value):
        identity = (value['attachmentId'], value['revision'])
        if identity not in positions:
            citations.append(value)
            positions[identity] = len(citations)
        return f'〔{positions[identity]}〕'
    for token, evidence in text.items():
        identifier, revision, ordinal = evidence
        key = '[[file:' + token + ']]'
        item, chunk = items[identifier], chunks.get(tuple(evidence))
        if item.extraction_revision != revision or chunk is None:
            replacements[key] = '（来源已变化）'
            continue
        replacements[key] = register({'attachmentId': identifier, 'revision': revision, 'ordinal': ordinal,
                                      'name': item.name, 'location': document_chunk_location(chunk.location)})
    for token, ref in pages.items():
        key = '[[page:' + token + ']]'
        item = items[ref['attachmentId']]
        if item.extraction_revision != ref['revision'] or item.sha256 != ref['sha256']:
            replacements[key] = '（来源已变化）'
            continue
        url = f'/api/v1/uploads/{item.id}/pages/{ref["page"]}?' + urlencode({key: ref[key] for key in ('revision', 'resolution', 'sheet', 'renderer')})
        replacements[key] = register({'attachmentId': item.id, 'revision': ref['revision'], 'ordinal': -ref['page'],
                                      'page': ref['page'], 'name': item.name, 'location': ref['location'], 'previewUrl': url})
    for ref in tables.values():
        item = items[ref['attachmentId']]
        if item.extraction_revision != ref['revision'] or item.sha256 != ref['sha256']:
            continue
        register({'attachmentId': item.id, 'revision': ref['revision'], 'sourceKind': 'table',
                  'name': item.name, 'location': ref['location'], 'sampleRows': ref['sampleRows'],
                  'rowCount': ref['rowCount'], 'sampleTruncated': ref['sampleTruncated'],
                  'contentUrl': f'/api/v1/uploads/{item.id}/content'})
    def replace_prose(prose):
        markers = re.compile(r'\[\[(file|page):([^\]\n]+)\]\]')
        for match in markers.finditer(prose):
            replacements.setdefault(match[0], '（来源未核实）' if match[1] == 'file' else '（页面未核实）')
        prose = normalize_citation_wrappers(prose, replacements)
        return markers.sub(lambda match: replacements[match[0]], prose)
    # A user's quoted example is content, not a request to manufacture a source.
    parts, start = [], 0
    for code in _CODE_SAMPLE.finditer(answer):
        parts.extend((replace_prose(answer[start:code.start()]), code[0]))
        start = code.end()
    parts.append(replace_prose(answer[start:]))
    return ''.join(parts), citations


class _MaterialCoverage(list):
    def __init__(self):
        super().__init__()
        # Retain exact prior-format notes for terminal-note replacement only.
        self.previous = []


async def material_coverage(db, actor, job, documents, reads):
    """Keep extracted-text reads distinct from files supplied for computation."""
    from app.modules.executions.models import SandboxExecution
    executions = (await db.scalars(select(SandboxExecution).where(SandboxExecution.job_id == job.id,
        SandboxExecution.owner_id == actor.id, SandboxExecution.company_id == actor.company_id,
        SandboxExecution.state == 'succeeded'))).all()
    coverage, legacy = _MaterialCoverage(), []
    complete, reused_complete = 0, 0
    for document in documents:
        if document.kind != 'document':
            continue
        read = len({entry[2] for entry in reads.values() if entry[0] == document.id and entry[1] == document.extraction_revision})
        info = document.extraction_info or {}
        total = info.get('chunks', 0)
        preloaded = any(token in job.result.get('documentPreloaded', []) for token, entry in reads.items()
                        if entry[0] == document.id and entry[1] == document.extraction_revision)
        reused = sum(token in job.result.get('documentReadAliases', {}) for token, entry in reads.items()
                     if entry[0] == document.id and entry[1] == document.extraction_revision)
        if document.extraction_status == 'failed':
            detail = '文字提取失败：' + document.extraction_info.get('error', '解析失败')
            old_detail = '未能使用：' + document.extraction_info.get('error', '解析失败')
        else:
            previously_preloaded = any(token in job.result.get('documentPreloaded', []) for token, entry in reads.items() if entry[0] == document.id)
            detail = f'已准备文字 {read}/{total} 个分段' if previously_preloaded else f'文字工具读取 {read}/{total} 个分段'
            old_detail = f'实际读取 {read}/{total} 个文字分段'
            if reused:
                detail = f'文字工具读取/复用 {read}/{total} 个分段，其中 {reused} 个复用自相同内容附件'
            if document.extraction_status == 'partial':
                detail += '；文件文字仅部分可读'
                old_detail += '；文件仅部分可读'
        related = [row for row in executions if any(source.get('kind') == 'attachment' and source.get('id') == document.id
            and source.get('revision') == document.extraction_revision and source.get('sha256') == document.sha256 for source in row.sources)]
        direct = any(ref.get('attachment_id') == document.id for row in related for ref in row.result.get('inputRefs', []))
        if direct:
            detail += '；原文件已提供给代码执行，具体读取范围未单独记录'
        elif related:
            detail += '；列为代码执行的关联来源，不能据此认定本轮已读取原文件'
        page_refs = [ref for ref in job.result.get('documentPagesProvided', {}).values()
                     if ref['attachmentId'] == document.id and ref['revision'] == document.extraction_revision]
        pages = sorted({ref['page'] for ref in page_refs})
        provided = len({entry[2] for entry in job.result.get('documentTextProvided', {}).values() if entry[0] == document.id and entry[1] == document.extraction_revision})
        if 'documentTextProvided' in job.result:
            detail += f'；本任务已向主模型提供 {provided} 个文字分段'
        if pages:
            detail += '；本任务已提供页面图片：' + '、'.join(map(str, pages))
        elif document.extraction_info.get('hasVisuals'):
            detail += '；图片部分未读取'
        if document.extraction_info.get('schema') == 1 and not document.extraction_info.get('sourceComplete'):
            detail += '；原文件仍有未提取范围'
        coverage.previous.append(document.name + '：' + detail)
        legacy.append(document.name + '：' + old_detail)

        # Only explicit delivery records permit a complete-text summary. A
        # preload/tool read alone does not prove delivery to the main model.
        fully_provided = 'documentTextProvided' in job.result and total > 0 and provided == total
        unextracted = info.get('schema') == 1 and not info.get('sourceComplete')
        if (fully_provided and read == total and document.extraction_status == 'ready'
                and not info.get('hasVisuals') and not info.get('convertedFormat') and not pages and not unextracted and not related):
            complete += 1
            reused_complete += bool(reused)
            continue
        if document.extraction_status == 'failed':
            detail = '文字提取失败：' + info.get('error', '解析失败')
        elif not total:
            detail = '未提取到可读文字'
        elif fully_provided:
            detail = '已提取文字已全部提供给主模型'
        elif 'documentTextProvided' in job.result:
            detail = f'仅向主模型提供 {provided}/{total} 段已提取文字，其余文字未提供' if provided else '文字尚未提供给主模型'
        elif preloaded:
            detail = f'文字已准备（{read}/{total} 段），未记录是否提供给主模型'
        else:
            detail = f'工具已读取 {read}/{total} 段文字' if read else f'尚未读取文字（共 {total} 段）'
        if reused:
            detail += f'；含 {reused} 段复用自相同内容附件'
        if document.extraction_status == 'partial':
            detail += '；文件文字仅部分可读'
        if direct:
            detail += '；原文件已提供给代码执行，具体读取范围未单独记录'
        elif related:
            detail += '；仅关联代码执行，不能据此认定已读取原文件'
        if pages:
            detail += '；已向主模型提供第 ' + '、'.join(map(str, pages)) + ' 页图片'
            if any(ref.get('imageComplete') is False for ref in page_refs):
                detail += '；所提供页面仍有图片区域未读取'
            if info.get('totalPages', 0) > len(pages):
                detail += '；其余页面图片未读取'
        elif info.get('hasVisuals'):
            detail += '；图片部分未读取'
        if info.get('convertedFormat'):
            detail += '；转换后内容，原件图形及版式是否完整未核验'
        if unextracted:
            detail += '；原文件仍有未提取范围'
        coverage.append(document.name + '：' + detail)
    if complete:
        summary = f'{complete} 份文件的已提取文字已全部提供给主模型'
        if reused_complete:
            summary += f'，其中 {reused_complete} 份复用了相同内容附件的文字'
        coverage.insert(0, summary)
    return coverage, legacy


def detach_material_coverage(answer, stored=None):
    """Separate a server scope footer from prose before building model history.

    New records match exact stored lines. Legacy records recognize only the
    server's fixed leading phrases. The note is one paragraph; subsequent image
    warnings and answer paragraphs are preserved as prose.
    """
    normalize = lambda value: re.sub(r'\s+', '', value)
    recorded = stored.get('materialCoverage') if isinstance(stored, dict) else None
    legacy_line = re.compile(
        r'(?:\d+ 份文件的已提取文字已全部提供给主模型'
        r'|[^\n]+：(?:实际读取 \d+/\d+ 个文字分段|已准备文字 \d+/\d+ 个分段'
        r'|文字工具读取(?:/复用)? \d+/\d+ 个分段|工具已读取 \d+/\d+ 段文字'
        r'|尚未读取文字（共 \d+ 段）|仅向主模型提供 \d+/\d+ 段已提取文字'
        r'|文字尚未提供给主模型|已提取文字已全部提供给主模型'
        r'|文字已准备（\d+/\d+ 段），未记录是否提供给主模型))')
    for marker in ('本次材料范围：', '材料范围：'):
        prefix, separator, tail = answer.rpartition('\n\n' + marker)
        if not separator and answer.startswith(marker):
            prefix, separator, tail = '', marker, answer[len(marker):]
        if not separator:
            continue
        paragraph, *following = re.split(r'\n[ \t]*\n', tail.strip(), maxsplit=1)
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        exact = recorded and normalize(paragraph) == normalize('\n'.join(recorded))
        legacy = not recorded and lines and all(legacy_line.match(line) for line in lines)
        if exact or legacy:
            return '\n\n'.join(part for part in (prefix.rstrip(), *following) if part), lines
    return answer, []


def append_material_coverage(answer, coverage, legacy):
    """Keep one authoritative current-turn scope footer; preserve answer prose."""
    if not coverage:
        return answer
    while True:
        original = answer
        for lines in (coverage, legacy, getattr(coverage, 'previous', []), None):
            answer, _ = detach_material_coverage(answer, {'materialCoverage': lines} if lines else None)
        if answer == original:
            break
    return answer + '\n\n本次材料范围：\n' + '\n'.join(coverage)
