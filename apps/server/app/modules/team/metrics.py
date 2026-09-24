from app.core.errors import problem
from app.core.periods import period_range
from app.db.base import now
from app.modules.members.models import Company, Member
from app.modules.members.serializers import member_dto
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import WorkItem, WorkRevision
from app.modules.work.queries import status_filter
from app.modules.work.serializers import revision_work
from app.security.access import valid as business_valid
from sqlalchemy import select


def blocked(work):
    return work.get('status') != 'done' and (work.get('status') == 'blocked' or bool(work.get('blocker', '').strip()))


async def team_data(db, actor, *, period='this_week', start=None, end=None, q='', status='', members='active'):
    status_filter(status)
    if members not in ('active', 'inactive', 'all'):
        problem(422, '员工范围无效')
    company = await db.get(Company, actor.company_id)
    lower, upper, date_range = period_range(company, period, start, end)
    query = select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee')
    if members != 'all':
        query = query.where(Member.active.is_(members == 'active'))
    if q.strip():
        query = query.where(Member.name.icontains(q.strip(), autoescape=True))
    people = list((await db.scalars(query.order_by(Member.created_at, Member.id))).all())
    owners = [member.id for member in people]
    details = {'messages': [], 'blocked': [], 'reports': []}
    summaries = {member.id: {'member': member_dto(member), 'work': [], 'workCount': 0, 'blockedCount': 0, 'lastMessageAt': None, 'reportCount': 0} for member in people}
    messages = (await db.scalars(select(Message).where(Message.company_id == actor.company_id, Message.owner_id.in_(owners), Message.deleted.is_(False), Message.created_at >= lower, Message.created_at < upper).order_by(Message.created_at.desc(), Message.id.desc()))).all()
    for message in messages:
        if not await business_valid(db, actor, message.access):
            continue
        entry = summaries[message.owner_id]
        if not entry['lastMessageAt']:
            entry['lastMessageAt'] = message.created_at.isoformat()
        details['messages'].append({'id': message.id, 'member': entry['member'], 'title': message.text[:180] or message.transcript[:180] or '附件上报', 'at': message.created_at.isoformat(), 'href': '/messages/' + message.id})
    # Read revisions before the cutoff, retaining the latest *accessible*
    # revision for each work. Later updates cannot rewrite a historical period.
    revisions = (await db.execute(select(WorkRevision, WorkItem).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id.in_(owners), WorkItem.deleted.is_(False), WorkRevision.company_id == actor.company_id, WorkRevision.created_at < upper).order_by(WorkRevision.work_id, WorkRevision.created_at.desc(), WorkRevision.revision.desc()))).all()
    seen = set()
    for revision, work in revisions:
        if work.id in seen or not await business_valid(db, actor, work.access, retained=True) or not await business_valid(db, actor, revision.access, retained=True):
            continue
        seen.add(work.id)
        if revision.created_at < lower or (status and revision.content.get('status') != status):
            continue
        dto = revision_work(work, revision)
        entry = summaries[work.owner_id]
        entry['workCount'] += 1
        entry['work'].append(dto)
        if blocked(dto):
            entry['blockedCount'] += 1
            details['blocked'].append({'id': work.id, 'member': entry['member'], 'title': dto['title'], 'at': dto['updatedAt'], 'href': f'/work/{work.id}?revision={revision.revision}', 'work': dto})
    reports = (await db.execute(select(ReportRevision, Report).join(Report, Report.id == ReportRevision.report_id).where(Report.company_id == actor.company_id, Report.owner_id.in_(owners), Report.deleted.is_(False), ReportRevision.company_id == actor.company_id, ReportRevision.created_at >= lower, ReportRevision.created_at < upper, ReportRevision.revision <= Report.published_revision).order_by(ReportRevision.created_at.desc(), ReportRevision.id.desc()))).all()
    seen = set()
    for revision, report in reports:
        if report.id in seen:
            continue
        seen.add(report.id)
        entry = summaries[report.owner_id]
        entry['reportCount'] += 1
        details['reports'].append({'id': report.id, 'member': entry['member'], 'title': report.period + (' 日报' if report.kind == 'daily' else ' 周报'), 'at': revision.created_at.isoformat(), 'href': f'/reports/{report.id}?revision={revision.revision}'})
    for entry in summaries.values():
        entry['work'].sort(key=lambda work: (work['updatedAt'], work['id']), reverse=True)
        entry['work'] = entry['work'][:1]  # A summary preview, never the count source.
    metrics = {'reported': sum(bool(entry['lastMessageAt']) for entry in summaries.values()), 'members': len(people), 'blocked': len(details['blocked']), 'reports': len(details['reports'])}
    return {'items': list(summaries.values()), 'metrics': metrics, 'range': date_range, 'updatedAt': now().isoformat()}, details
