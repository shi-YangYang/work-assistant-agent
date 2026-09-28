from app.core.errors import problem
from app.core.pagination import cursor_decode, cursor_encode
from app.core.periods import period_range
from app.db.base import now
from app.modules.members.models import Company, Member
from app.modules.members.serializers import member_dto
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.team.workspace import retained_filter
from app.modules.work.models import WorkItem, WorkRevision
from app.modules.work.queries import status_filter
from sqlalchemy import and_, func, or_, select, tuple_


def blocked(content):
    state = content['status'].astext
    return and_(state != 'done', or_(state == 'blocked', func.length(func.regexp_replace(func.coalesce(content['blocker'].astext, ''), r'\s', '', 'g')) > 0))


def work_dto(row):
    return {'id': row['id'], 'ownerId': row['owner_id'], 'dueDate': None, 'origin': row['origin'], **row['content'], 'revision': row['revision'], 'updatedAt': row['at'].isoformat(), 'historical': True, 'hasBusinessLinks': bool(row['business_links'])}


async def datasets(db, actor, lower, upper, owners, status):
    messages = select(Message.id, Message.owner_id, Message.text, Message.transcript, Message.created_at.label('at')).where(Message.company_id == actor.company_id, Message.owner_id.in_(owners), Message.deleted.is_(False), Message.private_context.is_(False), Message.created_at >= lower, Message.created_at < upper)
    messages = messages.where(await retained_filter(db, actor, messages, Message.access, retained=False)).subquery()
    works = select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id.in_(owners), WorkItem.deleted.is_(False))
    works = works.where(await retained_filter(db, actor, works, WorkItem.access)).subquery()
    revisions = select(WorkRevision).join(works, works.c.id == WorkRevision.work_id).where(WorkRevision.company_id == actor.company_id, WorkRevision.created_at < upper)
    revisions = revisions.where(await retained_filter(db, actor, revisions, WorkRevision.access))
    latest = revisions.distinct(WorkRevision.work_id).order_by(WorkRevision.work_id, WorkRevision.created_at.desc(), WorkRevision.revision.desc()).subquery()
    work = select(works.c.id, works.c.owner_id, works.c.origin, latest.c.content, latest.c.revision, latest.c.business_links, latest.c.created_at.label('at')).join(latest, latest.c.work_id == works.c.id).where(latest.c.created_at >= lower)
    if status:
        work = work.where(latest.c.content['status'].astext == status)
    work = work.subquery()
    reports = select(Report.id, Report.owner_id, Report.period, Report.kind, ReportRevision.revision, ReportRevision.created_at.label('at')).join(ReportRevision, ReportRevision.report_id == Report.id).where(Report.company_id == actor.company_id, Report.owner_id.in_(owners), Report.deleted.is_(False), ReportRevision.company_id == actor.company_id, ReportRevision.created_at >= lower, ReportRevision.created_at < upper, ReportRevision.revision <= Report.published_revision).distinct(Report.id).order_by(Report.id, ReportRevision.created_at.desc(), ReportRevision.id.desc()).subquery()
    return {'messages': messages, 'work': work, 'reports': reports}


async def team_data(db, actor, *, period='this_week', start=None, end=None, q='', status='', members='active', metric=None, cursor=None, limit=20):
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
    people = (await db.scalars(query.order_by(Member.created_at, Member.id))).all()
    entries = {member.id: {'member': member_dto(member), 'work': [], 'workCount': 0, 'blockedCount': 0, 'lastMessageAt': None, 'reportCount': 0} for member in people}
    rows = await datasets(db, actor, lower, upper, entries, status)
    messages, work, reports = (rows[key] for key in ('messages', 'work', 'reports'))
    message_count = 0
    for owner, count, last in (await db.execute(select(messages.c.owner_id, func.count(), func.max(messages.c.at)).group_by(messages.c.owner_id))).all():
        entries[owner]['lastMessageAt'] = last.isoformat()
        message_count += count
    for owner, count, block_count in (await db.execute(select(work.c.owner_id, func.count(), func.count().filter(blocked(work.c.content))).group_by(work.c.owner_id))).all():
        entries[owner].update(workCount=count, blockedCount=block_count)
    for owner, count in (await db.execute(select(reports.c.owner_id, func.count()).group_by(reports.c.owner_id))).all():
        entries[owner]['reportCount'] = count
    if metric is None:
        preview = select(work).distinct(work.c.owner_id).order_by(work.c.owner_id, work.c.at.desc(), work.c.id.desc())
        for row in (await db.execute(preview)).mappings():
            entries[row['owner_id']]['work'] = [work_dto(row)]
    metrics = {'reported': sum(bool(entry['lastMessageAt']) for entry in entries.values()), 'members': len(people), 'blocked': sum(entry['blockedCount'] for entry in entries.values()), 'reports': sum(entry['reportCount'] for entry in entries.values())}
    summary = {'items': list(entries.values()), 'metrics': metrics, 'range': date_range, 'updatedAt': now().isoformat()}
    if metric is None:
        return summary, None
    source = work if metric == 'blocked' else rows[metric]
    query = select(source)
    if metric == 'blocked':
        query = query.where(blocked(source.c.content))
    if cursor:
        query = query.where(tuple_(source.c.at, source.c.id) < cursor_decode(cursor))
    page = (await db.execute(query.order_by(source.c.at.desc(), source.c.id.desc()).limit(limit + 1))).mappings().all()
    details = []
    for row in page[:limit]:
        item = {'id': row['id'], 'member': entries[row['owner_id']]['member'], 'at': row['at'].isoformat()}
        if metric == 'messages':
            item.update(title=row['text'][:180] or row['transcript'][:180] or '附件上报', href='/messages/' + row['id'])
        elif metric == 'blocked':
            dto = work_dto(row)
            item.update(title=dto['title'], href=f"/work/{row['id']}?revision={row['revision']}", work=dto)
        else:
            item.update(title=row['period'] + (' 日报' if row['kind'] == 'daily' else ' 周报'), href=f"/reports/{row['id']}?revision={row['revision']}")
        details.append(item)
    total = message_count if metric == 'messages' else metrics[metric]
    return summary, {'items': details, 'nextCursor': cursor_encode(page[limit - 1]['at'], page[limit - 1]['id']) if len(page) > limit else None, 'total': total}
