import re
from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.db.idempotency import idem_begin, idem_save
from app.modules.announcements.models import Announcement, AnnouncementRead
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import defer


def visible(actor, state='published'):
    return select(Announcement).where(Announcement.company_id == actor.company_id, Announcement.state == state)


def read_join(actor):
    return and_(AnnouncementRead.announcement_id == Announcement.id,
                AnnouncementRead.reader_id == actor.id,
                AnnouncementRead.company_id == actor.company_id)


async def unread_count(db, actor):
    return await db.scalar(select(func.count()).select_from(Announcement).outerjoin(AnnouncementRead, read_join(actor)).where(
        Announcement.company_id == actor.company_id, Announcement.state == 'published',
        func.coalesce(AnnouncementRead.revision, 0) < Announcement.revision)) or 0


def summary_text(markdown):
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', markdown)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'^\s*(?:#{1,6}\s+|[-*+>]\s+|\d+[.)]\s+|```[^\n]*)', '', text, flags=re.MULTILINE)
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'[*_`~]+', '', text)
    return re.sub(r'\s+', ' ', text).strip()[:180]


def dto(item, read_revision=0, summary=None):
    result = {'id': item.id, 'title': item.title, 'state': item.state, 'revision': item.revision,
              'authorName': item.author_name, 'editorName': item.editor_name,
              'publishedAt': item.created_at.isoformat(), 'updatedAt': item.updated_at.isoformat(),
              'withdrawnAt': item.withdrawn_at.isoformat() if item.withdrawn_at else None,
              'unread': item.state == 'published' and (read_revision or 0) < item.revision}
    if summary is None:
        result['markdown'] = item.markdown
    else:
        result['summary'] = summary_text(summary)
    return result


async def page(db, actor, state, cursor):
    if state != 'published' and actor.role != 'admin':
        problem(403, '仅管理员可查看历史公告')
    query = visible(actor, state).options(defer(Announcement.markdown)).add_columns(
        AnnouncementRead.revision, func.substr(Announcement.markdown, 1, 1000)
    ).outerjoin(AnnouncementRead, read_join(actor)).order_by(Announcement.created_at.desc(), Announcement.id.desc())
    rows = (await db.execute(query.offset(cursor).limit(21))).all()
    return {'items': [dto(item, revision, summary) for item, revision, summary in rows[:20]],
            'nextCursor': str(cursor + 20) if len(rows) > 20 else None}


async def record(db, actor, identifier, *, management=False, lock=False):
    query = select(Announcement).where(Announcement.company_id == actor.company_id, Announcement.id == identifier)
    if not management:
        query = query.where(Announcement.state == 'published')
    elif actor.role != 'admin':
        problem(403, '仅管理员可管理公告')
    item = await db.scalar(query.with_for_update() if lock else query)
    if not item:
        problem(404, '公告已删除或不可用')
    return item


async def detail(db, actor, identifier, management):
    item = await record(db, actor, identifier, management=management)
    read_revision = await db.scalar(select(AnnouncementRead.revision).where(
        AnnouncementRead.announcement_id == item.id, AnnouncementRead.reader_id == actor.id,
        AnnouncementRead.company_id == actor.company_id))
    return dto(item, read_revision)


async def create(db, actor, body, key):
    prior, digest = await idem_begin(db, actor, 'announcement-publish', key, body.model_dump())
    if prior:
        return prior
    instant = now()
    item = Announcement(company_id=actor.company_id, title=body.title, markdown=body.markdown,
                        author_id=actor.id, author_name=actor.name, editor_id=actor.id,
                        editor_name=actor.name, created_at=instant, updated_at=instant)
    db.add(item)
    await db.flush()
    return idem_save(db, actor, 'announcement-publish', key, digest, dto(item))


async def update(db, actor, identifier, body):
    item = await record(db, actor, identifier, management=True, lock=True)
    if item.state != 'published':
        problem(409, '公告不可用，不能继续修改')
    version(item, body.expectedRevision)
    if (item.title, item.markdown) != (body.title, body.markdown):
        item.title, item.markdown = body.title, body.markdown
        item.revision += 1
        item.updated_at = now()
        item.editor_id, item.editor_name = actor.id, actor.name
    return dto(item)


async def delete_announcement(db, actor, identifier, body, key):
    action = 'announcement-delete:' + identifier
    prior, digest = await idem_begin(db, actor, action, key, body.model_dump())
    if prior:
        return prior
    item = await record(db, actor, identifier, management=True, lock=True)
    version(item, body.expectedRevision)
    await db.delete(item)
    await db.flush()
    return idem_save(db, actor, action, key, digest, {'ok': True})


async def mark_read(db, actor, identifier, body):
    item = await record(db, actor, identifier, lock=True)
    version(item, body.expectedRevision)
    statement = insert(AnnouncementRead).values(company_id=actor.company_id, announcement_id=item.id,
                                               reader_id=actor.id, revision=body.expectedRevision, read_at=now())
    await db.execute(statement.on_conflict_do_update(
        index_elements=['announcement_id', 'reader_id'],
        set_={'revision': body.expectedRevision, 'read_at': now()}))
    return {'ok': True}
