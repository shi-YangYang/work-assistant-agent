import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from app.core.errors import problem
from app.db.base import now
from app.modules.members.models import Company, Member
from app.modules.reports.models import Report, ReportRevision
from app.modules.team.sources import bounded_content, source_dto
from app.modules.work.models import WorkItem, WorkRevision
from app.security.access import employee, receipt, remember, scope
from sqlalchemy import Text, func, select
from zoneinfo import ZoneInfo


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
