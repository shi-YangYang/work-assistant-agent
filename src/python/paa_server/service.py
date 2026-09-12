"""Authorization, versioned business writes and report periods shared by API/tools."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo
from sqlalchemy import select
from fastapi import HTTPException
from .models import Company, Idempotency, Job, Member, Message, ProgressDraft, Report, WorkItem, WorkRevision, now


def problem(status, message, code=None):
    raise HTTPException(status_code=status, detail={'code': code or {404: 'not_found', 409: 'conflict', 403: 'forbidden'}.get(status, 'invalid_request'), 'message': message})


async def owned(db, model, identifier, actor, *, read=False, lock=False):
    query = select(model).where(model.id == identifier, model.company_id == actor.company_id)
    if not read or actor.role != 'admin':
        query = query.where(model.owner_id == actor.id)
    else:
        employees = select(Member.id).where(Member.company_id == actor.company_id, Member.role == 'employee')
        query = query.where((model.owner_id == actor.id) | model.owner_id.in_(employees))
    if lock:
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        problem(404, '记录不存在或无权查看')
    return item


def version(record, expected):
    if record.revision != expected:
        problem(409, '内容已在其他页面更新，请读取最新版本后再保存', 'revision_conflict')


async def idem_begin(db, actor, action, key, payload):
    if not key or len(key) > 100:
        problem(422, '缺少有效的操作编号')
    # Serializes all writes for this identity, including repeat concurrent requests.
    await db.scalar(select(Member).where(Member.id == actor.id).with_for_update())
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    existing = await db.scalar(select(Idempotency).where(Idempotency.owner_id == actor.id, Idempotency.action == action, Idempotency.key == key))
    if existing:
        if existing.digest != digest:
            problem(409, '同一操作编号不能用于不同内容')
        return existing.response, digest
    return None, digest


def idem_save(db, actor, action, key, digest, response):
    db.add(Idempotency(company_id=actor.company_id, owner_id=actor.id, action=action, key=key, digest=digest, response=response))
    return response


def period(kind, value: date):
    start = value if kind == 'daily' else value - timedelta(days=value.weekday())
    return start, start if kind == 'daily' else start + timedelta(days=6)


def period_bounds(report):
    zone = ZoneInfo(report.timezone)
    start = datetime.combine(date.fromisoformat(report.period), time.min, zone)
    end = datetime.combine(date.fromisoformat(report.period_end) + timedelta(days=1), time.min, zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def report_inputs(db, report):
    start, end = period_bounds(report)
    revisions = list((await db.scalars(select(WorkRevision).where(WorkRevision.owner_id == report.owner_id, WorkRevision.company_id == report.company_id, WorkRevision.created_at >= start, WorkRevision.created_at < end).order_by(WorkRevision.created_at, WorkRevision.id))).all())
    # Latest revision per work within the selected period, not today's rewritten state.
    latest = {r.work_id: r for r in revisions}
    return list(latest.values())


async def ensure_report(db, actor, kind, day, *, scheduled=False):
    company = await db.get(Company, actor.company_id)
    start, end = period(kind, day)
    await db.scalar(select(Member).where(Member.id == actor.id).with_for_update())
    report = await db.scalar(select(Report).where(Report.owner_id == actor.id, Report.kind == kind, Report.period == start.isoformat()))
    if report is None:
        report = Report(company_id=actor.company_id, owner_id=actor.id, kind=kind, period=start.isoformat(), period_end=end.isoformat(), timezone=company.rules['timezone'], content={'completed': '', 'ongoing': '', 'blockers': '', 'next': ''})
        db.add(report)
        await db.flush()
    existing = await db.scalar(select(Job).where(Job.owner_id == actor.id, Job.kind == 'report', Job.target_id == report.id).order_by(Job.created_at.desc()).limit(1))
    if existing is not None and (scheduled or existing.state in ('queued', 'running')):
        return report, existing
    inputs = await report_inputs(db, report)
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=report.id, base_revision=report.revision, state='queued' if inputs else 'succeeded', phase='saved' if inputs else 'empty', result={'sourceIds': [r.id for r in inputs]})
    db.add(job)
    await db.flush()
    return report, job


async def confirm_drafts(db, actor, items, ignore=False):
    drafts = [await owned(db, ProgressDraft, item.id, actor, lock=True) for item in sorted(items, key=lambda i: i.id)]
    for draft, item in zip(drafts, sorted(items, key=lambda i: i.id)):
        version(draft, item.expectedRevision)
        if draft.status != 'pending':
            problem(409, '这条建议已经处理')
    result = []
    for draft in drafts:
        if not ignore:
            if draft.work_id:
                work = await owned(db, WorkItem, draft.work_id, actor, lock=True)
                version(work, draft.base_revision)
                work.revision += 1
                work.content = draft.content
                work.title = draft.content['title']
                work.updated_at = now()
            else:
                work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=draft.content['title'], content=draft.content)
                db.add(work)
                await db.flush()
                draft.work_id = work.id
            db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=work.revision, content=work.content, source_ids=[draft.message_id]))
            result.append(work.id)
        draft.status = 'ignored' if ignore else 'confirmed'
        draft.revision += 1
    return result


def member_dto(member):
    return {'id': member.id, 'name': member.name, 'username': member.username, 'role': member.role, 'active': member.active, 'mustChangePassword': member.must_change_password}


def work_dto(work):
    return {'id': work.id, 'ownerId': work.owner_id, **work.content, 'revision': work.revision, 'updatedAt': work.updated_at.isoformat()}


def draft_dto(draft):
    return {'id': draft.id, 'messageId': draft.message_id, 'workId': draft.work_id, 'baseRevision': draft.base_revision, 'content': draft.content, 'status': draft.status, 'revision': draft.revision}


def job_dto(job):
    return {'id': job.id, 'kind': job.kind, 'targetId': job.target_id, 'state': job.state, 'phase': job.phase, 'error': job.error, 'updatedAt': job.updated_at.isoformat()}
