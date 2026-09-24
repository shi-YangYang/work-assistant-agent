from datetime import timedelta
from app.db.base import now
from app.modules.members.models import Member
from app.modules.model_services.models import ModelUsage
from app.modules.model_services.usage import interrupt_usage
from app.security.access import scope as business_scope
from app.security.locks import company_lock as business_company_lock
from app.tasks.feedback_state import update_feedback
from app.tasks.models import Job
from sqlalchemy import exists, select
from sqlalchemy.orm import aliased


async def interrupted_state(db, job):
    if job.result.get('reportSaved'):
        return 'queued'
    rows = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id, ModelUsage.job_attempt == job.attempt, ModelUsage.job_fence == job.fence))).all()
    # A reservation is not a sent request. Old jobs without request records use
    # their conservative legacy marker; never silently repeat an unknown call.
    sent = any(row.started_at is not None for row in rows) if rows else job.request_started
    return 'awaiting_retry' if sent else 'queued'


async def claim(sessions, owner_id=None, *, company_id=None):
    scope = [*([Job.owner_id == owner_id] if owner_id else []), *([Job.company_id == company_id] if company_id else [])]
    async with sessions() as db:
        expired = (await db.execute(select(Job.id, Job.company_id, Job.owner_id).where(Job.state == 'running', Job.lease_until < now(), *scope).order_by(Job.created_at, Job.id).limit(50))).all()
    for identifier, company, owner in expired:
        async with sessions.begin() as db:
            await business_company_lock(db, company)
            actor = await db.scalar(select(Member).where(Member.id == owner).with_for_update())
            job = await db.scalar(select(Job).where(Job.id == identifier).with_for_update())
            if job.state != 'running' or job.lease_until is None or job.lease_until >= now():
                continue
            await interrupt_usage(db, job)
            update_feedback(job)
            job.state = await interrupted_state(db, job)
            if job.state == 'queued':
                job.request_started = False
            if not actor.active or (job.kind == 'report' and actor.role != 'employee'):
                job.state = 'cancelled'
            job.error = '处理意外中断，请确认后重试' if job.state == 'awaiting_retry' else ''
            job.lease_until, job.fence, job.updated_at = None, job.fence + 1, now()
    async with sessions.begin() as db:
        running = aliased(Job)
        query = select(Job).join(Member, Member.id == Job.owner_id).where(Job.state == 'queued', Member.active.is_(True), ((Job.kind != 'report') | (Member.role == 'employee')), ~exists(select(running.id).where(running.owner_id == Job.owner_id, running.state == 'running')), *scope).order_by(Job.created_at, Job.id)
        company = await db.scalar(query.with_only_columns(Job.company_id).limit(1))
        if not company:
            return None
        # Same order as all API/harness writes, including expired-lease recovery.
        await business_company_lock(db, company)
        job = await db.scalar(query.where(Job.company_id == company).with_for_update(of=(Job, Member), skip_locked=True).limit(1))
        if not job:
            return None
        if not job.access:
            job.access = business_scope(await db.get(Member, job.owner_id))
        job.state, job.fence, job.lease_until, job.updated_at = 'running', job.fence + 1, now() + timedelta(seconds=90), now()
        update_feedback(job, 'preparing', '')
        return job
