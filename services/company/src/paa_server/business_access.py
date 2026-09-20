"""Server-owned team evidence. Shared by tools, reads, confirmation and recovery.

The access envelope contains identities/version references, never source text. A
short company advisory transaction lock precedes owner/job locks everywhere that
can publish or delete derived data; no network request holds it.
"""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from sqlalchemy import Text, func, select, text
from fastapi import HTTPException
from .models import Attachment, Company, DocumentChunk, Job, Member, Message, ProgressDraft, Report, ReportRevision, WorkItem, WorkRevision, now
from .service import problem


async def company_lock(db, company_id):
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))'), {'scope': 'business:' + company_id})


def scope(actor):
    return {'actorId': actor.id, 'companyId': actor.company_id, 'role': actor.role, 'team': False, 'reads': {}}


def role_valid(actor, access):
    return bool(actor) and (not access or not access.get('team') or (actor.active and access.get('actorId') == actor.id and access.get('companyId') == actor.company_id and (not access.get('team') or actor.role == 'admin')))


async def employee(db, actor, identifier):
    if not actor.active or actor.role != 'admin':
        problem(403, '当前账号不能查询团队业务')
    member = await db.scalar(select(Member).where(Member.id == identifier, Member.company_id == actor.company_id, Member.role == 'employee'))
    if not member:
        problem(404, '员工不存在或无权查看')
    return member


async def resolve(db, actor, evidence, *, latest=False, retained=False):
    """Recheck every reference from the database, not from model-supplied claims."""
    if evidence.get('type') == 'own_work':
        work = await db.scalar(select(WorkItem).where(WorkItem.id == evidence['id'], WorkItem.owner_id == actor.id, WorkItem.company_id == actor.company_id, WorkItem.deleted.is_(False)))
        if not work or not role_valid(actor, work.access):
            problem(404, '本人事项已删除或无权查看')
        return work, actor
    member = await employee(db, actor, evidence['ownerId'])
    kind, identifier = evidence['type'], evidence['id']
    model = {'member': Member, 'work': WorkItem, 'report': Report, 'message': Message, 'document': Attachment}.get(kind)
    if not model:
        problem(404, '来源不存在或无权查看')
    if kind == 'member':
        return member, member
    if retained:
        return None, member
    item = await db.scalar(select(model).where(model.id == identifier, model.company_id == actor.company_id, model.owner_id == member.id))
    if not item or item.deleted:
        problem(404, '来源已删除或无权查看')
    if kind == 'work':
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.id == evidence.get('versionId'), WorkRevision.work_id == item.id, WorkRevision.owner_id == member.id, WorkRevision.company_id == actor.company_id))
        if not revision or revision.access.get('team'):
            problem(404, '工作修订不存在或无权查看')
        if latest and item.revision != revision.revision:
            problem(409, '关联工作已更新，请重新查询后生成建议', 'source_changed')
        return revision, member
    if kind == 'report':
        revision = await db.scalar(select(ReportRevision).where(ReportRevision.id == evidence.get('versionId'), ReportRevision.report_id == item.id, ReportRevision.owner_id == member.id, ReportRevision.company_id == actor.company_id))
        if not revision or revision.revision > item.published_revision:
            problem(404, '报告版本尚未提交或已删除')
        if latest and item.published_revision != revision.revision:
            problem(409, '关联报告已重新提交，请重新查询后生成建议', 'source_changed')
        return revision, member
    parent = evidence.get('parent')
    if not isinstance(parent, dict) or parent.get('ownerId') != member.id or parent.get('type') not in ('work', 'report', 'message'):
        problem(404, '来源没有可访问的业务关联')
    record, _ = await resolve(db, actor, parent, latest=latest)
    if kind == 'message':
        if parent['type'] == 'work':
            source_ids = record.source_ids
        elif parent['type'] == 'report':
            revisions = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(record.source_ids), WorkRevision.owner_id == member.id, WorkRevision.company_id == actor.company_id))).all()
            source_ids = [mid for r in revisions for mid in r.source_ids]
        else:
            problem(404, '消息没有可访问的业务关联')
        if item.id not in source_ids:
            problem(404, '消息不属于所引用业务')
        if latest and item.transcript_revision != evidence.get('version'):
            problem(409, '关联语音文字已更新，请重新查询', 'source_changed')
    elif kind == 'document':
        if parent['type'] != 'message' or item.message_id != record.id or item.kind != 'document':
            problem(404, '文件不属于所引用消息')
        if item.extraction_revision != evidence.get('version'):
            problem(409, '文件提取版本已变化，请重新查询', 'source_changed')
    return item, member


async def valid(db, actor, access, *, latest=False, retained=False):
    if not role_valid(actor, access):
        return False
    if not access or not access.get('team'):
        return True
    if access.get('invalidated') and not retained:
        return False
    try:
        for evidence in access.get('reads', {}).values():
            await resolve(db, actor, evidence, latest=latest, retained=retained)
    except (HTTPException, KeyError, TypeError, RecursionError):
        return False
    return True


async def require(db, actor, access, *, latest=False, retained=False):
    if not await valid(db, actor, access, latest=latest, retained=retained):
        problem(409 if latest else 403, '关联资料已变化或无权查看，请重新查询；旧内容不会继续使用', 'business_access_changed')


def merge_access(base, inherited):
    if not inherited or not inherited.get('team'):
        return base
    reads = {**base.get('reads', {}), **inherited.get('reads', {})}
    if len(reads) > 500:
        problem(422, '本次引用范围过大，请缩小查询范围')
    return {**inherited, **base, 'team': True, 'reads': reads, **({'invalidated': True} if base.get('invalidated') or inherited.get('invalidated') else {})}


def merge_links(*groups):
    """Keep server-verified associations when an edit changes the target/source."""
    links = {link['token']: link for group in groups for link in group or []}
    if len(links) > 500:
        problem(422, '本次引用范围过大，请缩小查询范围')
    return list(links.values())


def inherit(actor, target, *sources, include_message_links=False):
    """An ordinary edit cannot remove the restrictions of content it reuses.

    Callers authorize sources before calling this function. Retention after a
    source deletion remains a read rule for confirmed work, not a way to clear
    the provenance on a new draft or revision.
    """
    access = target.access or scope(actor)
    links = getattr(target, 'business_links', [])
    for source in sources:
        access = merge_access(access, source.access)
        source_links = getattr(source, 'business_links', [])
        if include_message_links and isinstance(source, Message):
            source_links = [{'token': token, 'evidence': evidence} for token, evidence in source.access.get('reads', {}).items() if evidence.get('type') in ('work', 'report')]
        links = merge_links(links, source_links)
    target.access = access
    if hasattr(target, 'business_links'):
        target.business_links = links


def receipt(kind, record, *, version=None, parent=None, ordinal=None):
    item = {'type': kind, 'id': record.work_id if kind == 'work' else record.report_id if kind == 'report' else record.id, 'ownerId': record.owner_id if kind != 'member' else record.id}
    if kind in ('work', 'report'):
        item.update(versionId=record.id, version=record.revision)
    elif version is not None:
        item['version'] = version
    if parent:
        item['parent'] = parent
    if ordinal is not None:
        item['ordinal'] = ordinal
    return item


def remember(job, actor, evidence):
    token = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()[:24]
    job.access = merge_access(job.access or scope(actor), {'team': True, 'reads': {token: evidence}})
    return token


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


def date_range(company, period='current', start='', end=''):
    zone = ZoneInfo(company.rules['timezone'])
    today = now().astimezone(zone).date()
    if period == 'current':
        return None, None, {'mode': 'current', 'timezone': str(zone), 'queriedAt': now().isoformat()}
    if period == 'recent':
        first, last = today - timedelta(days=6), today
    elif period in ('this_week', 'last_week'):
        first = today - timedelta(days=today.weekday() + (7 if period == 'last_week' else 0))
        last = first + timedelta(days=6)
    elif period == 'custom':
        try:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            problem(422, '请提供开始和结束日期 YYYY-MM-DD')
        if last < first or (last - first).days > 366:
            problem(422, '日期范围须在一年内且结束日期不早于开始日期')
    else:
        problem(422, '时间范围无效')
    return datetime.combine(first, time.min, zone).astimezone(timezone.utc), datetime.combine(last + timedelta(days=1), time.min, zone).astimezone(timezone.utc), {'mode': period, 'start': first.isoformat(), 'end': last.isoformat(), 'timezone': str(zone), 'queriedAt': now().isoformat()}


def cursor_offset(job, fingerprint, cursor):
    if not cursor:
        return 0
    saved = (job.result.get('businessCursors') or {}).get(cursor)
    if not saved or saved['filter'] != fingerprint:
        problem(422, '分页位置不属于当前查询，请从第一页开始')
    return saved['offset']


def next_cursor(job, fingerprint, offset):
    token = hashlib.sha256(f'{job.id}:{fingerprint}:{offset}'.encode()).hexdigest()[:32]
    cursors = {**job.result.get('businessCursors', {}), token: {'filter': fingerprint, 'offset': offset}}
    job.result = {**job.result, 'businessCursors': cursors}
    return token


async def find_members(db, actor, job, query):
    if actor.role != 'admin':
        problem(403, '当前账号不能查询团队业务')
    stmt = select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee')
    if query:
        stmt = stmt.where(Member.name.icontains(query[:80], autoescape=True))
    count = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    all_members = (await db.scalars(stmt.order_by(Member.name, Member.id).limit(501))).all()
    if len(all_members) > 500:
        problem(422, '匹配员工超过 500 人，请补充姓名后查询')
    members = all_members[:20]
    job.access = {**(job.access or scope(actor)), 'team': True}
    for member in all_members:
        remember(job, actor, receipt('member', member))
    return {'items': [{'id': m.id, 'name': m.name, 'active': m.active} for m in members], 'total': count, 'hasMore': count > 20, 'clarificationRequired': len(members) > 1 and bool(query)}


async def query_business(db, actor, job, *, kind='work', employee_ids=None, query='', status='', period='current', start='', end='', cursor=''):
    if actor.role != 'admin':
        problem(403, '当前账号不能查询团队业务')
    if kind not in ('work', 'report') or status not in ('', 'in_progress', 'blocked', 'done') or len(employee_ids or []) > 20:
        problem(422, '查询条件无效')
    for identifier in employee_ids or []:
        member = await employee(db, actor, identifier)
        remember(job, actor, receipt('member', member))
    company = await db.get(Company, actor.company_id)
    first, last, window = date_range(company, period, start, end)
    members = select(Member.id).where(Member.company_id == actor.company_id, Member.role == 'employee')
    if employee_ids:
        members = members.where(Member.id.in_(employee_ids))
    if kind == 'work':
        revision = WorkRevision
        stmt = select(revision).join(WorkItem, WorkItem.id == revision.work_id).where(WorkItem.deleted.is_(False), revision.company_id == actor.company_id, revision.owner_id.in_(members), revision.access['team'].as_boolean().is_not(True))
        if first:
            # Latest change *inside* this period, not the current WorkItem content.
            ranked = select(WorkRevision.id, func.row_number().over(partition_by=WorkRevision.work_id, order_by=(WorkRevision.created_at.desc(), WorkRevision.revision.desc())).label('rank')).where(WorkRevision.company_id == actor.company_id, WorkRevision.owner_id.in_(members), WorkRevision.created_at >= first, WorkRevision.created_at < last).subquery()
            stmt = stmt.where(revision.id.in_(select(ranked.c.id).where(ranked.c.rank == 1)))
        else:
            stmt = stmt.where(revision.revision == WorkItem.revision)
        if status:
            stmt = stmt.where(revision.content['status'].astext == status)
    else:
        revision = ReportRevision
        stmt = select(revision).join(Report, Report.id == revision.report_id).where(Report.deleted.is_(False), revision.company_id == actor.company_id, revision.owner_id.in_(members), revision.revision == Report.published_revision)
        if first:
            stmt = stmt.where(Report.period <= window['end'], Report.period_end >= window['start'])
    if query:
        stmt = stmt.where(func.cast(revision.content, Text).icontains(query[:120], autoescape=True))
    fingerprint = hashlib.sha256(json.dumps([actor.id, actor.company_id, kind, sorted(employee_ids or []), query, status, window.get('start'), window.get('end'), period], sort_keys=True).encode()).hexdigest()
    offset = cursor_offset(job, fingerprint, cursor)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    counts = {}
    if kind == 'work':
        grouped = stmt.subquery()
        state = grouped.c.content['status'].astext
        counts = dict((await db.execute(select(state, func.count()).group_by(state))).all())
    rows = (await db.scalars(stmt.order_by(revision.created_at.desc(), revision.id).offset(offset).limit(20))).all()
    job.access = {**(job.access or scope(actor)), 'team': True}
    items = []
    for row in rows:
        evidence = receipt(kind, row)
        token = remember(job, actor, evidence)
        dto = await source_dto(db, actor, evidence, token)
        remaining = 450
        clipped = {}
        for key, value in dto['content'].items():
            clipped[key] = value[:min(120 if key != 'summary' else 180, remaining)]
            remaining -= len(clipped[key])
        dto['content'] = clipped
        dto['contentTruncated'] = clipped != bounded_content(row.content, None)
        dto['citation'] = f'[[business:{token}]]'
        items.append(dto)
    # Aggregate results also depend on the records not shown in the first page.
    # Store a bounded range receipt by version IDs; refuse a misleading untracked total.
    all_rows = (await db.scalars(stmt.limit(501))).all()
    if len(all_rows) > 500:
        problem(422, '匹配记录超过 500 条，请限定员工、日期或关键词后查询')
    for row in all_rows:
        remember(job, actor, receipt(kind, row))
    query_scope = {**window, 'kind': kind, 'employeeIds': employee_ids or 'all_employees', 'total': total, 'returned': len(items), 'offset': offset, 'query': query, 'status': status}
    job.result = {**job.result, 'businessQueries': [*job.result.get('businessQueries', []), query_scope][-16:]}
    return {'items': items, 'total': total, 'statusCounts': counts, 'hasMore': offset + len(items) < total, 'nextCursor': next_cursor(job, fingerprint, offset + len(items)) if offset + len(items) < total else None, 'scope': {**window, 'employeeIds': employee_ids or 'all_employees', 'includedInactiveEmployees': True, 'offset': offset, 'returned': len(items)}, 'coverage': '仅已确认工作／已提交报告；contentTruncated 表示正文是否裁剪，已给出的完整字段可直接用于回答或关联。需要缺失正文或原始材料时再读取来源。'}


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


async def invalidate_deleted(db, company_id):
    """Invalidate all dependent owners while the caller holds the company lock."""
    jobs = (await db.scalars(select(Job).where(Job.company_id == company_id, Job.access['team'].as_boolean().is_(True)).with_for_update())).all()
    for job in jobs:
        actor = await db.get(Member, job.owner_id)
        if actor and await valid(db, actor, job.access):
            continue
        job.access = {**job.access, 'invalidated': True}
        if job.state in ('queued', 'running', 'failed', 'awaiting_retry'):
            job.state, job.phase, job.error, job.lease_until = 'cancelled', 'business_access_changed', '关联资料已删除或权限已变化，请重新提问', None
            job.fence += 1
        job.result = {}
        for table in ('checkpoint_writes', 'checkpoint_blobs', 'checkpoints'):
            if await db.scalar(text('SELECT to_regclass(:table)'), {'table': table}):
                await db.execute(text(f'DELETE FROM {table} WHERE thread_id LIKE :prefix'), {'prefix': f'{company_id}:{job.owner_id}:job:{job.id}%'})
    messages = (await db.scalars(select(Message).where(Message.company_id == company_id, Message.access['team'].as_boolean().is_(True)))).all()
    for message in messages:
        actor = await db.get(Member, message.owner_id)
        if actor and await valid(db, actor, message.access):
            continue
        message.reply, message.citations, message.suggestions = '', [], []
        message.access = {**message.access, 'invalidated': True}
        for draft in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == message.id, ProgressDraft.status == 'pending'))).all():
            draft.status, draft.content = 'deleted', {}
            draft.revision += 1


async def work_for_model(db, actor, job, work):
    from .service import work_dto
    await require(db, actor, work.access, retained=True)
    result = work_dto(work)
    if not work.access.get('team'):
        return result
    # A confirmed follow-up is its owner's independent business fact. After its
    # raw source was deleted, use only that fact, never the previous raw context.
    remember(job, actor, {'type': 'own_work', 'id': work.id, 'ownerId': actor.id, 'version': work.revision})
    related = []
    for link in work.business_links:
        try:
            _, member = await resolve(db, actor, link['evidence'])
            remember(job, actor, receipt('member', member))
            related.append({'type': link['evidence']['type'], 'id': link['evidence']['id'], 'employeeId': member.id, 'employeeName': member.name})
        except HTTPException:
            related.append({'unavailable': True})
    result['relatedBusiness'] = related
    return result


async def query_summary(db, queries):
    groups = {}
    for query in queries:
        key = json.dumps({k: v for k, v in query.items() if k not in ('queriedAt', 'offset', 'returned')}, sort_keys=True)
        group = groups.setdefault(key, {'query': query, 'pages': set()})
        group['pages'].add((query['offset'], query['returned']))
    lines = []
    for group in groups.values():
        q = group['query']
        people = '本公司全部员工（含停用员工历史业务）' if q['employeeIds'] == 'all_employees' else '、'.join([(await db.get(Member, identifier)).name for identifier in q['employeeIds']])
        kind = '工作' if q['kind'] == 'work' else '已提交报告'
        period = ('当前状态' if q['kind'] == 'work' else '当前已提交版本') if q['mode'] == 'current' else q['start'] + ' 至 ' + q['end']
        filters = ('；关键词：' + q['query']) if q.get('query') else ''
        if q.get('status'):
            filters += '；状态：' + {'blocked': '有阻碍', 'done': '已完成', 'in_progress': '进行中'}[q['status']]
        pages = '、'.join(f'{offset + 1}～{offset + count}' for offset, count in sorted(group['pages']) if count)
        covered = f'已展示第 {pages} 条' if pages else '没有匹配记录'
        at = datetime.fromisoformat(q['queriedAt']).astimezone(ZoneInfo(q['timezone'])).strftime('%Y-%m-%d %H:%M')
        lines.append(f'- {kind} · {people} · {period}{filters}：共 {q["total"]} 条，{covered}。查询于 {at}（{q["timezone"]}）。')
    return '\n\n查询依据：\n' + '\n'.join(lines) if lines else ''
