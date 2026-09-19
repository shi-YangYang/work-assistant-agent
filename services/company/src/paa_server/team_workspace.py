"""Manager work and reporting views, with one filter scope for rows and counts."""
from datetime import date

from fastapi import Query
from sqlalchemy import select

from . import business_access as business
from .models import Company, Member, Report, ReportObligation, ReportRevision, WorkItem, WorkRevision, now
from .queries import blocked, period_range, revision_work, status_filter
from .report_schedule import obligation_dto
from .service import member_dto, problem, work_dto


async def employees(db, actor, scope, member):
    if scope not in ('active', 'inactive', 'all'):
        problem(422, '员工范围无效')
    query = select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee')
    if scope != 'all':
        query = query.where(Member.active.is_(scope == 'active'))
    people = list((await db.scalars(query.order_by(Member.name, Member.id))).all())
    return people, {p.id: p for p in people if not member or p.id == member}


def page(rows, offset):
    return {'items': rows[offset:offset + 20], 'total': len(rows), 'nextCursor': str(offset + 20) if len(rows) > offset + 20 else None}


async def work_view(db, actor, *, scope='current', period='this_week', start=None, end=None, q='', status='', members='active', member='', offset=0):
    status_filter(status)
    if scope not in ('current', 'updated'):
        problem(422, '工作查看范围无效')
    people, owners = await employees(db, actor, members, member)
    company = await db.get(Company, actor.company_id)
    lower, upper, date_range = period_range(company, period, start, end)
    query = select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id.in_(owners), WorkItem.deleted.is_(False))
    rows = []
    for work in (await db.scalars(query)).all():
        if not await business.valid(db, actor, work.access, retained=True):
            continue
        dto = work_dto(work)
        if scope == 'updated':
            revisions = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == work.id, WorkRevision.company_id == actor.company_id, WorkRevision.created_at < upper).order_by(WorkRevision.created_at.desc(), WorkRevision.revision.desc()))).all()
            revision = None
            for candidate in revisions:
                if await business.valid(db, actor, candidate.access, retained=True):
                    revision = candidate
                    break
            if not revision or revision.created_at < lower:
                continue
            dto = revision_work(work, revision)
        person = owners[work.owner_id]
        if q.strip().casefold() not in ' '.join([person.name, *(str(dto.get(key, '')) for key in ('title', 'summary', 'blocker', 'nextStep'))]).casefold():
            continue
        rows.append({'id': work.id, 'member': member_dto(person), 'work': dto})
    counts = {'all': len(rows), 'in_progress': sum(r['work']['status'] != 'done' for r in rows), 'blocked': sum(blocked(r['work']) for r in rows), 'done': sum(r['work']['status'] == 'done' for r in rows)}
    if status:
        rows = [r for r in rows if (blocked(r['work']) if status == 'blocked' else r['work']['status'] != 'done' if status == 'in_progress' else r['work']['status'] == 'done')]
    rows.sort(key=lambda r: (r['work']['updatedAt'], r['id']), reverse=True)
    return {**page(rows, offset), 'counts': counts, 'range': date_range, 'members': [member_dto(p) for p in people]}


async def report_view(db, actor, *, kind='daily', period='this_week', start=None, end=None, q='', status='', members='active', member='', offset=0):
    if kind not in ('daily', 'weekly') or status not in ('', 'expected', 'pending', 'overdue', 'submitted', 'cancelled'):
        problem(422, '汇报筛选无效')
    people, owners = await employees(db, actor, members, member)
    company = await db.get(Company, actor.company_id)
    _, _, date_range = period_range(company, period, start, end)
    first, last = date_range['start'], date_range['end']
    instant = now()
    # Periods overlap the selected dates; submission time does not change the
    # period a report belongs to. Include published reports without a schedule.
    reports = (await db.scalars(select(Report).where(Report.company_id == actor.company_id, Report.owner_id.in_(owners), Report.kind == kind, Report.deleted.is_(False), Report.published_revision > 0, Report.period <= last, Report.period_end >= first))).all()
    published = {}
    for report in reports:
        revision = await db.scalar(select(ReportRevision).where(ReportRevision.report_id == report.id, ReportRevision.company_id == actor.company_id, ReportRevision.revision == report.published_revision))
        if revision:
            published[(report.owner_id, report.period)] = (report, revision)
    obligations = (await db.scalars(select(ReportObligation).where(ReportObligation.company_id == actor.company_id, ReportObligation.owner_id.in_(owners), ReportObligation.kind == kind, ReportObligation.period <= last, ReportObligation.period_end >= first))).all()
    entries = {(r.owner_id, r.period): (r, published.pop((r.owner_id, r.period), None)) for r in obligations}
    entries.update({key: (None, value) for key, value in published.items()})
    rows = []
    for (owner, _), (obligation, submitted) in entries.items():
        person = owners[owner]
        report, revision = submitted or (None, None)
        state = 'submitted' if report else obligation_dto(obligation, instant)['state']
        summary = ' · '.join(text.strip() for text in (revision.content.get(key, '') for key in ('completed', 'ongoing', 'blockers', 'next')) if isinstance(text, str) and text.strip())[:300] if revision else ''
        if q.strip().casefold() not in (person.name + ' ' + summary).casefold():
            continue
        rows.append({'id': obligation.id if obligation else report.id, 'member': member_dto(person), 'kind': kind, 'period': obligation.period if obligation else report.period, 'periodEnd': obligation.period_end if obligation else report.period_end, 'state': state, 'scheduled': bool(obligation and obligation.state != 'cancelled'), 'deadlineAt': obligation.deadline_at.isoformat() if obligation else None, 'timezone': obligation.timezone if obligation else report.timezone, 'reportId': report.id if report else None, 'revision': revision.revision if revision else None, 'submittedAt': revision.created_at.isoformat() if revision else None, 'summary': summary})
    counts = {'all': sum(r['state'] != 'cancelled' for r in rows), 'cancelled': sum(r['state'] == 'cancelled' for r in rows), 'expected': sum(r['scheduled'] for r in rows), 'submitted': sum(r['state'] == 'submitted' for r in rows), 'pending': sum(r['state'] in ('pending', 'overdue') for r in rows), 'overdue': sum(r['state'] == 'overdue' for r in rows)}
    if status:
        rows = [r for r in rows if (r['scheduled'] if status == 'expected' else r['state'] in ('pending', 'overdue') if status == 'pending' else r['state'] == status)]
    if not status:
        rows = [r for r in rows if r['state'] != 'cancelled']
    rows.sort(key=lambda r: (r['period'], r['member']['name'], r['id']), reverse=True)
    return {**page(rows, offset), 'counts': counts, 'range': date_range, 'members': [member_dto(p) for p in people]}


def register_routes(app, ADMIN, DB):
    @app.get('/api/v1/team/workspace/{view}')
    async def workspace(view: str, scope: str = 'current', kind: str = 'daily', period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', member: str = '', offset: int = Query(0, ge=0), actor=ADMIN, db=DB):
        params = dict(period=period, start=start, end=end, q=q, status=status, members=members, member=member, offset=offset)
        if view == 'work':
            return await work_view(db, actor, scope=scope, **params)
        if view == 'reports':
            return await report_view(db, actor, kind=kind, **params)
        problem(404, '查看页面不存在')
