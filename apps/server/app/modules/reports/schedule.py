import logging
from datetime import datetime, time, timedelta
from app.core.errors import problem
from app.db.base import now
from app.modules.members.models import Member
from app.modules.reports.models import Report, ReportEligibility, ReportNotification, ReportObligation, ReportRevision, ReportSchedule
from app.modules.reports.periods import period
from app.tasks.models import Job
from sqlalchemy import delete, exists, func, select
from zoneinfo import ZoneInfo

log = logging.getLogger('paa.company')


def next_period(kind, instant, zone):
    start, end = period(kind, instant.astimezone(ZoneInfo(zone)).date())
    return (end + timedelta(days=1)).isoformat()


async def save_schedule(db, company, instant=None):
    instant = instant or now()
    for kind in ('daily', 'weekly'):
        effective = next_period(kind, instant, company.rules['timezone'])
        db.add(ReportSchedule(company_id=company.id, kind=kind, revision=company.revision, timezone=company.rules['timezone'], rule=company.rules[kind], effective_period=effective, next_period=effective))


async def effective_periods(db, company):
    rows = (await db.scalars(select(ReportSchedule).where(ReportSchedule.company_id == company.id).order_by(ReportSchedule.revision.desc()))).all()
    result = {}
    for row in rows:
        result.setdefault(row.kind, row.effective_period)
    return result


async def eligibility_changed(db, member, instant=None):
    instant = instant or now()
    current = await db.scalar(select(ReportEligibility).where(ReportEligibility.owner_id == member.id, ReportEligibility.ends_at.is_(None)).with_for_update())
    eligible = member.active and member.role == 'employee'
    if current and not eligible:
        current.ends_at = instant
    elif not current and eligible:
        db.add(ReportEligibility(company_id=member.company_id, owner_id=member.id, starts_at=instant))
    if not eligible:
        from app.modules.model_services.usage import interrupt_usage
        from app.tasks.feedback_state import update_feedback
        jobs = (await db.scalars(select(Job).where(Job.owner_id == member.id, Job.state.in_(('queued', 'running', 'failed', 'awaiting_retry'))).with_for_update())).all()
        for job in jobs:
            await interrupt_usage(db, job)
            job.state, job.error, job.lease_until = 'cancelled', '账号权限已变化，本次处理已停止', None
            job.fence, job.updated_at = job.fence + 1, instant
            update_feedback(job)
        rows = (await db.scalars(select(ReportObligation).where(ReportObligation.owner_id == member.id, ReportObligation.state == 'pending').with_for_update())).all()
        for row in rows:
            row.state = 'cancelled'
        await db.execute(delete(ReportNotification).where(ReportNotification.owner_id == member.id))


async def link_report(db, report, *, submitted=False, cancelled=False):
    obligation = await db.scalar(select(ReportObligation).where(ReportObligation.owner_id == report.owner_id, ReportObligation.kind == report.kind, ReportObligation.period == report.period).with_for_update())
    if not obligation:
        return
    obligation.report_id = report.id
    if cancelled:
        obligation.state = 'cancelled'
    elif submitted and obligation.state != 'cancelled':
        obligation.state = 'submitted'
        obligation.submitted_at = obligation.submitted_at or now()
    if obligation.state != 'pending':
        await db.execute(delete(ReportNotification).where(ReportNotification.obligation_id == obligation.id))


async def notify(db, obligation, stage, instant):
    if not obligation.reminders or obligation.state != 'pending':
        return
    ranks = {'ready': 0, 'due': 1, 'overdue': 2}
    existing = await db.scalar(select(ReportNotification).where(ReportNotification.obligation_id == obligation.id).with_for_update())
    if existing:
        if ranks[stage] > ranks[existing.stage]:
            existing.stage, existing.updated_at, existing.read_at = stage, instant, None
    else:
        db.add(ReportNotification(company_id=obligation.company_id, owner_id=obligation.owner_id, obligation_id=obligation.id, stage=stage, updated_at=instant))


async def draft_ready(db, report):
    obligation = await db.scalar(select(ReportObligation).where(ReportObligation.owner_id == report.owner_id, ReportObligation.kind == report.kind, ReportObligation.period == report.period).with_for_update())
    if obligation:
        obligation.report_id = report.id
        await notify(db, obligation, 'ready', now())


async def materialize(db, schedule, start, budget):
    start, end = period(schedule.kind, start)
    rule = schedule.rule
    trigger = start if schedule.kind == 'daily' else start + timedelta(days=rule['days'][0])
    if trigger.weekday() not in rule['days']:
        return 0, True
    zone = ZoneInfo(schedule.timezone)
    period_start = datetime.combine(start, time.min, zone)
    query = select(Member).where(Member.company_id == schedule.company_id, Member.active.is_(True), Member.role == 'employee', exists(select(ReportEligibility.id).where(ReportEligibility.owner_id == Member.id, ReportEligibility.starts_at <= period_start, (ReportEligibility.ends_at.is_(None) | (ReportEligibility.ends_at > period_start)))), ~exists(select(ReportObligation.id).where(ReportObligation.owner_id == Member.id, ReportObligation.kind == schedule.kind, ReportObligation.period == start.isoformat()))).order_by(Member.id)
    members = (await db.scalars(query.limit(budget + 1))).all()
    for member in members[:budget]:
        await db.scalar(select(Member).where(Member.id == member.id).with_for_update())
        report = await db.scalar(select(Report).where(Report.owner_id == member.id, Report.kind == schedule.kind, Report.period == start.isoformat()))
        active_interval = await db.scalar(select(ReportEligibility).where(ReportEligibility.owner_id == member.id, ReportEligibility.starts_at <= period_start, (ReportEligibility.ends_at.is_(None) | (ReportEligibility.ends_at > period_start))).order_by(ReportEligibility.starts_at.desc()).limit(1))
        revoked = active_interval is not None and active_interval.ends_at is not None
        submitted = await db.scalar(select(func.min(ReportRevision.created_at)).where(ReportRevision.report_id == report.id)) if report and report.published_revision else None
        db.add(ReportObligation(company_id=schedule.company_id, owner_id=member.id, kind=schedule.kind, period=start.isoformat(), period_end=end.isoformat(), timezone=schedule.timezone, rule_revision=schedule.revision, generate_at=datetime.combine(trigger, time.fromisoformat(rule['generateTime']), zone), deadline_at=datetime.combine(trigger, time.fromisoformat(rule['deadline']), zone), reminders=rule.get('reminders', True), before_minutes=rule.get('beforeMinutes', 30), report_id=report.id if report else None, state='cancelled' if report and report.deleted else 'submitted' if submitted else 'cancelled' if revoked else 'pending', submitted_at=submitted))
    await db.flush()
    return min(len(members), budget), len(members) <= budget


def obligation_dto(row, instant, *, name=None, own=False, job=None):
    return {'id': row.id, 'ownerId': row.owner_id, 'name': name, 'kind': row.kind, 'period': row.period, 'periodEnd': row.period_end, 'timezone': row.timezone, 'deadlineAt': row.deadline_at.isoformat(), 'state': 'overdue' if row.state == 'pending' and row.deadline_at <= instant else row.state, 'submittedAt': row.submitted_at.isoformat() if row.submitted_at else None, 'reportId': row.report_id if row.state != 'cancelled' and (own or row.state == 'submitted') else None, **({'job': job} if own else {})}


async def obligation_page(db, actor, *, kind='daily', status='', selected_period=None, cursor=0, team=False, instant=None):
    instant = instant or now()
    if kind not in ('daily', 'weekly') or status not in ('', 'pending', 'overdue', 'submitted', 'cancelled'):
        problem(422, '汇报筛选无效')
    base = select(ReportObligation, Member.name).join(Member, Member.id == ReportObligation.owner_id).where(ReportObligation.company_id == actor.company_id, ReportObligation.kind == kind)
    if not team:
        base = base.where(ReportObligation.owner_id == actor.id)
    if selected_period:
        start, _ = period(kind, selected_period)
        base = base.where(ReportObligation.period == start.isoformat())
    counts = dict((await db.execute(base.with_only_columns(ReportObligation.state, func.count()).group_by(ReportObligation.state))).all())
    overdue = await db.scalar(select(func.count()).select_from(base.where(ReportObligation.state == 'pending', ReportObligation.deadline_at <= instant).subquery()))
    if status == 'overdue':
        base = base.where(ReportObligation.state == 'pending', ReportObligation.deadline_at <= instant)
    elif status:
        base = base.where(ReportObligation.state == status)
        if status == 'pending':
            base = base.where(ReportObligation.deadline_at > instant)
    rows = (await db.execute(base.order_by(ReportObligation.period.desc(), ReportObligation.owner_id).offset(cursor).limit(21))).all()
    from app.tasks.serializers import job_dto
    items = []
    for row, name in rows[:20]:
        job = await db.scalar(select(Job).where(Job.target_id == row.report_id, Job.kind == 'report').order_by(Job.created_at.desc(), Job.id.desc()).limit(1)) if not team and row.report_id else None
        items.append(obligation_dto(row, instant, name=name if team else None, own=not team, job=job_dto(job) if job else None))
    return {'period': period(kind, selected_period)[0].isoformat() if selected_period else None, 'items': items, 'nextCursor': str(cursor + 20) if len(rows) > 20 else None, 'counts': {'expected': counts.get('pending', 0) + counts.get('submitted', 0), 'submitted': counts.get('submitted', 0), 'pending': counts.get('pending', 0), 'overdue': overdue, 'cancelled': counts.get('cancelled', 0)}}
