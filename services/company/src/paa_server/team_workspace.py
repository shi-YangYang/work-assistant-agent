"""Manager work and reporting views, with one filter scope for rows and counts."""
from datetime import date

from fastapi import Query
from sqlalchemy import and_, case, func, literal, or_, select

from . import business_access as business
from .models import Company, Member, Report, ReportObligation, ReportRevision, WorkItem, WorkRevision, now
from .queries import period_range, status_filter
from .service import member_dto, problem

PAGE_SIZE = 20


async def employees(db, actor, scope, member):
    if scope not in ('active', 'inactive', 'all'):
        problem(422, '员工范围无效')
    query = select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee')
    if scope != 'all':
        query = query.where(Member.active.is_(scope == 'active'))
    people = list((await db.scalars(query.order_by(Member.name, Member.id))).all())
    return people, {p.id: p for p in people if not member or p.id == member}


async def retained_filter(db, actor, query, access):
    # Ordinary employee records need no reference lookups. For team-derived
    # content, keep the existing policy and validate each distinct envelope once,
    # before either pagination or counts. Never authorize only the visible page.
    ordinary = or_(access['team'].is_(None), access.contains({'team': False}), access.contains({'team': None}))
    envelopes = (await db.scalars(query.with_only_columns(access).order_by(None).where(~ordinary).distinct())).all()
    allowed = [envelope for envelope in envelopes if await business.valid(db, actor, envelope, retained=True)]
    return or_(ordinary, access.in_(allowed)) if allowed else ordinary


def search_text(name, content, keys):
    return func.concat_ws(' ', name, *(content[key].astext for key in keys))


async def page(db, rows, counts, selected, order, offset):
    totals = (await db.execute(select(*(func.count().filter(predicate).label(key) for key, predicate in counts.items()), func.count().filter(selected).label('total')).select_from(rows))).one()._mapping
    items = (await db.execute(select(rows).where(selected).order_by(*order).offset(offset).limit(PAGE_SIZE))).mappings().all()
    return items, {'total': totals['total'], 'nextCursor': str(offset + PAGE_SIZE) if totals['total'] > offset + PAGE_SIZE else None, 'counts': {key: totals[key] for key in counts}}


async def work_view(db, actor, *, scope='current', period='this_week', start=None, end=None, q='', status='', members='active', member='', offset=0):
    status_filter(status)
    if scope not in ('current', 'updated'):
        problem(422, '工作查看范围无效')
    people, owners = await employees(db, actor, members, member)
    company = await db.get(Company, actor.company_id)
    lower, upper, date_range = period_range(company, period, start, end)
    base = select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id.in_(owners), WorkItem.deleted.is_(False))
    base = base.where(await retained_filter(db, actor, base, WorkItem.access))
    current = base.subquery()
    content, revision, updated, links = current.c.content, current.c.revision, current.c.updated_at, current.c.business_links
    source = current
    if scope == 'updated':
        candidates = select(WorkRevision).join(current, current.c.id == WorkRevision.work_id).where(WorkRevision.company_id == actor.company_id, WorkRevision.created_at < upper)
        candidates = candidates.where(await retained_filter(db, actor, candidates, WorkRevision.access))
        # Select the latest accessible revision before the cutoff first. Applying
        # search/status/the lower bound earlier would resurrect obsolete matches.
        latest = candidates.distinct(WorkRevision.work_id).order_by(WorkRevision.work_id, WorkRevision.created_at.desc(), WorkRevision.revision.desc()).subquery()
        source = current.join(latest, latest.c.work_id == current.c.id)
        content, revision, updated, links = latest.c.content, latest.c.revision, latest.c.created_at, latest.c.business_links
    query = select(current.c.id, current.c.owner_id, current.c.origin, content.label('content'), revision.label('revision'), updated.label('updated_at'), (func.jsonb_array_length(links) > 0).label('has_links')).select_from(source).join(Member, Member.id == current.c.owner_id)
    if scope == 'updated':
        query = query.where(updated >= lower)
    if q.strip():
        query = query.where(search_text(Member.name, content, ('title', 'summary', 'blocker', 'nextStep')).icontains(q.strip(), autoescape=True))
    rows = query.subquery()
    state = rows.c.content['status'].astext
    blocked = and_(state != 'done', or_(state == 'blocked', func.length(func.regexp_replace(func.coalesce(rows.c.content['blocker'].astext, ''), r'\s', '', 'g')) > 0))
    predicates = {'all': literal(True), 'in_progress': state != 'done', 'blocked': blocked, 'done': state == 'done'}
    items, result = await page(db, rows, predicates, predicates[status or 'all'], [rows.c.updated_at.desc(), rows.c.id.desc()], offset)
    entries = []
    for item in items:
        dto = {'id': item['id'], 'ownerId': item['owner_id'], 'dueDate': None, 'origin': item['origin'], **item['content'], 'revision': item['revision'], 'updatedAt': item['updated_at'].isoformat(), 'hasBusinessLinks': item['has_links']}
        if scope == 'updated':
            dto['historical'] = True
        entries.append({'id': item['id'], 'member': member_dto(owners[item['owner_id']]), 'work': dto})
    return {**result, 'items': entries, 'range': date_range, 'members': [member_dto(p) for p in people]}


async def report_view(db, actor, *, kind='daily', period='this_week', start=None, end=None, q='', status='', members='active', member='', offset=0):
    if kind not in ('daily', 'weekly') or status not in ('', 'expected', 'pending', 'overdue', 'submitted', 'cancelled'):
        problem(422, '汇报筛选无效')
    people, owners = await employees(db, actor, members, member)
    company = await db.get(Company, actor.company_id)
    _, _, date_range = period_range(company, period, start, end)
    first, last = date_range['start'], date_range['end']
    # Join only the published revision, never the mutable draft. Period overlap
    # determines inclusion even when the employee submitted a report later.
    published = select(Report.id, Report.owner_id, Report.period, Report.period_end, Report.timezone, ReportRevision.revision, ReportRevision.content, ReportRevision.created_at).join(ReportRevision, and_(ReportRevision.report_id == Report.id, ReportRevision.company_id == actor.company_id, ReportRevision.revision == Report.published_revision)).where(Report.company_id == actor.company_id, Report.owner_id.in_(owners), Report.kind == kind, Report.deleted.is_(False), Report.published_revision > 0, Report.period <= last, Report.period_end >= first).subquery()
    obligations = select(ReportObligation).where(ReportObligation.company_id == actor.company_id, ReportObligation.owner_id.in_(owners), ReportObligation.kind == kind, ReportObligation.period <= last, ReportObligation.period_end >= first).subquery()
    p, o = published.c, obligations.c
    owner = func.coalesce(o.owner_id, p.owner_id)
    state = case((p.id.is_not(None), 'submitted'), (and_(o.state == 'pending', o.deadline_at <= now()), 'overdue'), else_=o.state)
    scheduled = and_(o.id.is_not(None), o.state != 'cancelled')
    query = select(func.coalesce(o.id, p.id).label('id'), owner.label('owner_id'), Member.name.label('name'), func.coalesce(o.period, p.period).label('period'), func.coalesce(o.period_end, p.period_end).label('period_end'), state.label('state'), scheduled.label('scheduled'), o.deadline_at, func.coalesce(o.timezone, p.timezone).label('timezone'), p.id.label('report_id'), p.revision, p.created_at.label('submitted_at'), p.content).select_from(obligations.join(published, and_(o.owner_id == p.owner_id, o.period == p.period), full=True)).join(Member, Member.id == owner)
    if q.strip():
        query = query.where(search_text(Member.name, p.content, ('completed', 'ongoing', 'blockers', 'next')).icontains(q.strip(), autoescape=True))
    rows = query.subquery()
    r = rows.c
    predicates = {'all': r.state != 'cancelled', 'cancelled': r.state == 'cancelled', 'expected': r.scheduled, 'submitted': r.state == 'submitted', 'pending': r.state.in_(('pending', 'overdue')), 'overdue': r.state == 'overdue'}
    items, result = await page(db, rows, predicates, predicates[status or 'all'], [r.period.desc(), r.name.desc(), r.id.desc()], offset)
    entries = []
    for item in items:
        content = item['content'] or {}
        summary = ' · '.join(text.strip() for text in (content.get(key, '') for key in ('completed', 'ongoing', 'blockers', 'next')) if isinstance(text, str) and text.strip())[:300]
        entries.append({'id': item['id'], 'member': member_dto(owners[item['owner_id']]), 'kind': kind, 'period': item['period'], 'periodEnd': item['period_end'], 'state': item['state'], 'scheduled': item['scheduled'], 'deadlineAt': item['deadline_at'].isoformat() if item['deadline_at'] else None, 'timezone': item['timezone'], 'reportId': item['report_id'], 'revision': item['revision'], 'submittedAt': item['submitted_at'].isoformat() if item['submitted_at'] else None, 'summary': summary})
    return {**result, 'items': entries, 'range': date_range, 'members': [member_dto(p) for p in people]}


def register_routes(app, ADMIN, DB):
    @app.get('/api/v1/team/workspace/{view}')
    async def workspace(view: str, scope: str = 'current', kind: str = 'daily', period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', member: str = '', offset: int = Query(0, ge=0), actor=ADMIN, db=DB):
        params = dict(period=period, start=start, end=end, q=q, status=status, members=members, member=member, offset=offset)
        if view == 'work':
            return await work_view(db, actor, scope=scope, **params)
        if view == 'reports':
            return await report_view(db, actor, kind=kind, **params)
        problem(404, '查看页面不存在')
