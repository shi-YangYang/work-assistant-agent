"""Authorized list and period queries shared by dashboard summaries and drilldowns."""
import base64
from datetime import datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from . import business_access as business
from .models import Company, Member, Message, Report, ReportRevision, WorkItem, WorkRevision, now
from .service import member_dto, problem, work_dto


def cursor_encode(instant, identifier):
    return base64.urlsafe_b64encode(json.dumps([instant.isoformat(), identifier]).encode()).decode().rstrip('=')


def cursor_decode(value):
    try:
        if len(value) > 200:
            raise ValueError()
        stamp, identifier = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        instant = datetime.fromisoformat(stamp)
        if not instant.tzinfo or not isinstance(identifier, str) or len(identifier) > 36:
            raise ValueError()
        return instant, identifier
    except (ValueError, TypeError, UnicodeError):
        problem(422, '分页位置无效，请重新打开列表')


def status_filter(status):
    if status not in ('', 'in_progress', 'blocked', 'done'):
        problem(422, '工作状态无效')


def period_range(company, period='this_week', start=None, end=None, instant=None):
    zone = ZoneInfo(company.rules['timezone'])
    today = (instant or now()).astimezone(zone).date()
    if period == 'custom':
        if not start or not end or start > end:
            problem(422, '请选择有效的开始与结束日期')
    elif period == 'today':
        start = end = today
    elif period == 'this_week':
        start, end = today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6)
    elif period == 'this_month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    else:
        problem(422, '日期范围无效')
    return datetime.combine(start, time.min, zone), datetime.combine(end + timedelta(days=1), time.min, zone), {'period': period, 'start': start.isoformat(), 'end': end.isoformat(), 'timezone': zone.key}


async def work_page(db, actor, owner_id, q='', status='', cursor=None, limit=20):
    status_filter(status)
    query = select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id == owner_id, WorkItem.deleted.is_(False))
    if q.strip():
        query = query.where(or_(WorkItem.title.icontains(q.strip(), autoescape=True), *(WorkItem.content[key].astext.icontains(q.strip(), autoescape=True) for key in ('summary', 'blocker', 'nextStep'))))
    if status:
        query = query.where(WorkItem.content['status'].astext == status)
    visible = []
    boundary = cursor_decode(cursor) if cursor else None
    # Authorization may reject an arbitrarily long run of rows. Keep scanning
    # until a complete visible page (plus lookahead) or the actual end is found.
    while len(visible) <= limit:
        statement = query
        if boundary:
            stamp, identifier = boundary
            statement = statement.where((WorkItem.updated_at < stamp) | ((WorkItem.updated_at == stamp) & (WorkItem.id < identifier)))
        rows = list((await db.scalars(statement.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).limit(100))).all())
        for row in rows:
            if await business.valid(db, actor, row.access, retained=True):
                visible.append(row)
                if len(visible) > limit:
                    break
        if len(rows) < 100 or len(visible) > limit:
            break
        boundary = rows[-1].updated_at, rows[-1].id
    return {'items': [work_dto(row) for row in visible[:limit]], 'nextCursor': cursor_encode(visible[limit - 1].updated_at, visible[limit - 1].id) if len(visible) > limit else None}


def revision_work(work, revision):
    return {**work_dto(work), 'dueDate': None, **revision.content, 'revision': revision.revision, 'updatedAt': revision.created_at.isoformat(), 'historical': True, 'hasBusinessLinks':bool(revision.business_links)}


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
        if not await business.valid(db, actor, message.access):
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
        if work.id in seen or not await business.valid(db, actor, work.access, retained=True) or not await business.valid(db, actor, revision.access, retained=True):
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


def detail_page(rows, cursor=None, limit=20):
    rows = sorted(rows, key=lambda row: (datetime.fromisoformat(row['at']), row['id']), reverse=True)
    if cursor:
        boundary = cursor_decode(cursor)
        rows = [row for row in rows if (datetime.fromisoformat(row['at']), row['id']) < boundary]
    return {'items': rows[:limit], 'nextCursor': cursor_encode(datetime.fromisoformat(rows[limit - 1]['at']), rows[limit - 1]['id']) if len(rows) > limit else None}
