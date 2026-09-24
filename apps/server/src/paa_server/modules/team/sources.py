import re
from fastapi import HTTPException
from paa_server.core.errors import problem
from paa_server.modules.attachments.models import Attachment, DocumentChunk
from paa_server.modules.messages.models import Message
from paa_server.modules.reports.models import Report
from paa_server.modules.work.models import WorkItem, WorkRevision
from paa_server.security.access import receipt, remember, resolve
from sqlalchemy import select


async def business_link_dtos(db, actor, links):
    items = []
    for link in links:
        try:
            item = await source_dto(db, actor, link['evidence'], link['token'])
            items.append({k: v for k, v in item.items() if k not in ('content', 'sourceIds')})
        except HTTPException:
            items.append({'kind': 'business', 'unavailable': True})
    return items


def bounded_content(content, length=1200):
    return {key: str(value)[:length] for key, value in content.items() if key in ('title', 'summary', 'status', 'blocker', 'nextStep', 'completed', 'ongoing', 'blockers', 'next')}


async def source_dto(db, actor, evidence, token=''):
    if evidence.get('type') not in ('member', 'work', 'report', 'message', 'document'):
        problem(404, '该读取凭据不提供原始业务投影')
    record, member = await resolve(db, actor, evidence)
    kind = evidence['type']
    base = {'kind': 'business', 'token': token, 'objectType': kind, 'objectId': evidence['id'], 'ownerId': member.id, 'employeeName': member.name, 'employeeActive': member.active, 'revision': evidence.get('version', 0)}
    if kind == 'member':
        return {**base, 'title': member.name, 'at': member.created_at.isoformat(), 'content': {'name': member.name}}
    if kind == 'work':
        current = await db.get(WorkItem, evidence['id'])
        return {**base, 'title': record.content['title'], 'at': record.created_at.isoformat(), 'currentRevision': current.revision, 'content': bounded_content(record.content, 4000)}
    if kind == 'report':
        report = await db.get(Report, evidence['id'])
        return {**base, 'title': ('日报 ' if report.kind == 'daily' else '周报 ') + report.period, 'at': record.created_at.isoformat(), 'currentRevision': report.published_revision, 'period': report.period, 'periodEnd': report.period_end, 'content': bounded_content(record.content, 8000)}
    if kind == 'message':
        # Deliberately no conversation, reply, pending drafts or assistant metadata.
        text_value = record.transcript if record.transcript_revision == evidence['version'] else next((h['text'] for h in record.transcript_history if h['revision'] == evidence['version']), '')
        return {**base, 'title': '原始上报', 'at': record.created_at.isoformat(), 'content': {'text': record.text[:8000], 'transcript': text_value[:8000]}}
    chunk = await db.scalar(select(DocumentChunk).where(DocumentChunk.attachment_id == record.id, DocumentChunk.revision == evidence['version'], DocumentChunk.ordinal == evidence.get('ordinal', 0)))
    if not chunk:
        problem(404, '文件文字段落不存在或未提取')
    return {**base, 'title': record.name, 'at': record.created_at.isoformat(), 'location': chunk.location, 'content': {'text': chunk.text}, 'ordinal': chunk.ordinal, 'nextCursor': chunk.ordinal + 1 if chunk.ordinal + 1 < record.extraction_info.get('chunks', 0) else None, 'coverage': '本次仅返回一个已提取文字段落，未读取图片／扫描内容。'}


def canonical_token(value):
    match = re.fullmatch(r'(?:\[\[business:|business:)?([0-9a-f]{24})(?:\]\])?', value.strip())
    return match[1] if match else value


async def read_source(db, actor, job, token, child_id='', start=0):
    token = canonical_token(token)
    evidence = job.access.get('reads', {}).get(token)
    if not evidence or evidence.get('type') not in ('work', 'report', 'message', 'document'):
        problem(404, '来源未被本次查询读取')
    record, _ = await resolve(db, actor, evidence)
    if child_id:
        if evidence['type'] in ('work', 'report'):
            message = await db.get(Message, child_id)
            if not message:
                problem(404, '来源不存在或无权查看')
            evidence = receipt('message', message, version=message.transcript_revision, parent=evidence)
        elif evidence['type'] == 'message':
            attachment = await db.get(Attachment, child_id)
            if not attachment:
                problem(404, '来源不存在或无权查看')
            evidence = receipt('document', attachment, version=attachment.extraction_revision, parent=evidence, ordinal=max(0, min(start, 2000)))
        else:
            problem(422, '文件段落不包含其他业务来源')
        await resolve(db, actor, evidence)
        token = remember(job, actor, evidence)
    dto = await source_dto(db, actor, evidence, token)
    dto['citation'] = f'[[business:{token}]]'
    if evidence['type'] == 'report':
        records = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(record.source_ids), WorkRevision.owner_id == record.owner_id, WorkRevision.company_id == actor.company_id))).all()
        dto['sourceMessageIds'] = list(dict.fromkeys(mid for r in records for mid in r.source_ids))[:40]
    elif evidence['type'] == 'work':
        dto['sourceMessageIds'] = record.source_ids[:40]
    elif evidence['type'] == 'message':
        attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == evidence['id'], Attachment.deleted.is_(False)))).all()
        dto['attachments'] = []
        for attachment in attachments:
            if attachment.kind == 'document':
                remember(job, actor, receipt('document', attachment, version=attachment.extraction_revision, parent=evidence))
                dto['attachments'].append({'id': attachment.id, 'kind': 'document', 'name': attachment.name, 'status': attachment.extraction_status, 'chunks': attachment.extraction_info.get('chunks', 0)})
        dto['unreadMedia'] = {'images': sum(a.kind == 'image' for a in attachments), 'audio': sum(a.kind == 'audio' for a in attachments)}
        dto['coverage'] = '仅原始文字和已有转写；未读取图片、音频原件，也不会自动识图或转写。'
    remaining = 6000
    content = {}
    for key, value in dto['content'].items():
        content[key] = value[:min(2000, remaining)]
        remaining -= len(content[key])
    if content != dto['content']:
        dto['content'] = content
        dto['contentTruncated'] = True
        dto['coverage'] = (dto.get('coverage', '') + ' 正文仅返回节选，不能声称已读取全文；可在来源页面查看对应版本。').strip()
    return dto


async def citations(db, actor, access, answer):
    result, cited = [], []
    for token in re.findall(r'\[\[business:([^\]]+)\]\]', answer):
        evidence = access.get('reads', {}).get(token)
        if evidence and evidence.get('type') in ('work', 'report', 'message', 'document') and token not in cited:
            dto = await source_dto(db, actor, evidence, token)
            result.append({k: v for k, v in dto.items() if k not in ('content', 'sourceIds')})
            cited.append(token)
    answer = re.sub(r'\[\[business:([^\]]+)\]\]', lambda m: f'〔来源 {cited.index(m[1]) + 1}〕' if m[1] in cited else '', answer)
    # Even an omitted marker must not erase the provenance of an answer.
    if not result:
        for token, evidence in access.get('reads', {}).items():
            if evidence['type'] in ('work', 'report') and len(result) < 20:
                dto = await source_dto(db, actor, evidence, token)
                result.append({k: v for k, v in dto.items() if k not in ('content', 'sourceIds')})
    return answer, result
