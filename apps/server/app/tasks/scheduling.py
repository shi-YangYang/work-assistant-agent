from datetime import date, timedelta
from app.db.base import now
from app.modules.members.models import Company, Member
from app.modules.reports.models import ReportEligibility, ReportNotification, ReportObligation, ReportSchedule
from app.modules.reports.periods import period
from app.modules.reports.schedule import eligibility_changed, link_report, log, materialize, notify, save_schedule
from app.modules.reports.service import ensure_report
from app.security.locks import company_lock as business_company_lock
from sqlalchemy import and_, delete, exists, func, or_, select
from zoneinfo import ZoneInfo


async def schedule_company(sessions, company_id, instant, batch):
    async with sessions.begin() as db:
        await business_company_lock(db, company_id)
        company = await db.get(Company, company_id)
        schedules = (await db.scalars(select(ReportSchedule).where(ReportSchedule.company_id == company_id).order_by(ReportSchedule.kind, ReportSchedule.effective_period, ReportSchedule.revision).with_for_update())).all()
        if not schedules:
            await save_schedule(db, company, company.rules_effective_at)
            await db.flush()
            schedules = (await db.scalars(select(ReportSchedule).where(ReportSchedule.company_id == company_id).order_by(ReportSchedule.kind, ReportSchedule.revision))).all()
        members = (await db.scalars(select(Member).where(Member.company_id == company_id, Member.active.is_(True), Member.role == 'employee', ~exists(select(ReportEligibility.id).where(ReportEligibility.owner_id == Member.id))).limit(batch))).all()
        for member in members:
            await eligibility_changed(db, member, member.created_at)
        await db.flush()
        # Reserve a bounded pass for today's periods, regardless of history cursor.
        remaining = batch
        for kind in ('daily', 'weekly'):
            applicable = []
            for schedule in schedules:
                current = period(kind, instant.astimezone(ZoneInfo(schedule.timezone)).date())[0]
                if schedule.kind == kind and schedule.effective_period <= current.isoformat():
                    applicable.append((schedule, current))
            if applicable and remaining:
                schedule, current = max(applicable, key=lambda pair: pair[0].revision)
                if schedule.rule.get('enabled'):
                    used, _ = await materialize(db, schedule, current, remaining)
                    remaining -= used
        # A separate budget prevents a long outage from starving present work.
        remaining = batch
        for schedule in schedules:
            successors = [s for s in schedules if s.kind == schedule.kind and s.revision > schedule.revision]
            until = min((s.effective_period for s in successors), default='9999-12-31')
            current = period(schedule.kind, instant.astimezone(ZoneInfo(schedule.timezone)).date())[0].isoformat()
            if not schedule.rule.get('enabled'):
                continue
            while remaining > 0 and schedule.next_period <= current and schedule.next_period < until:
                start = date.fromisoformat(schedule.next_period)
                used, complete = await materialize(db, schedule, start, remaining)
                remaining -= max(1, used)
                if complete:
                    schedule.next_period = (period(schedule.kind, start)[1] + timedelta(days=1)).isoformat()
                else:
                    break
    async with sessions.begin() as db:
        await business_company_lock(db, company_id)
        # Filter already reconciled rows out in SQL, otherwise a recent page of
        # unchanged pending reports could starve older deadlines indefinitely.
        n, o = ReportNotification, ReportObligation
        near = o.deadline_at - func.make_interval(0, 0, 0, 0, 0, o.before_minutes)
        notification_due = and_(o.reminders.is_(True), or_(and_(o.deadline_at <= instant, or_(n.id.is_(None), n.stage != 'overdue')), and_(near <= instant, o.deadline_at > instant, or_(n.id.is_(None), n.stage == 'ready'))))
        eligible = or_(and_(o.generation_checked.is_(False), o.generate_at <= instant), notification_due, Member.active.is_(False), Member.role != 'employee')
        rows = (await db.scalars(select(o).join(Member, Member.id == o.owner_id).outerjoin(n, n.obligation_id == o.id).where(o.company_id == company_id, o.state == 'pending', eligible).order_by(o.period.desc(), o.id).limit(batch).with_for_update(of=o, skip_locked=True))).all()
        for row in rows:
            member = await db.scalar(select(Member).where(Member.id == row.owner_id).with_for_update())
            if not member.active or member.role != 'employee':
                row.state = 'cancelled'
                await db.execute(delete(n).where(n.obligation_id == row.id))
                continue
            if not row.generation_checked and row.generate_at <= instant:
                if row.deadline_at >= instant:
                    report, _ = await ensure_report(db, member, row.kind, date.fromisoformat(row.period), scheduled=True, report_timezone=row.timezone)
                    row.report_id = report.id
                    if report.published_revision:
                        await link_report(db, report, submitted=True)
                    elif any(report.content.values()) or report.candidate:
                        await notify(db, row, 'ready', instant)
                row.generation_checked = True
            if instant >= row.deadline_at:
                await notify(db, row, 'overdue', instant)
            elif instant >= row.deadline_at - timedelta(minutes=row.before_minutes):
                await notify(db, row, 'due', instant)


async def schedule_once(sessions, instant=None, batch=50):
    instant = instant or now()
    async with sessions() as db:
        companies = (await db.scalars(select(Company.id).order_by(Company.id))).all()
    for company_id in companies:
        try:
            await schedule_company(sessions, company_id, instant, batch)
        except Exception as error:
            log.warning('report schedule company=%s failure_type=%s', company_id, type(error).__name__)
