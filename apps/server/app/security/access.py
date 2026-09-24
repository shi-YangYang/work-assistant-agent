import hashlib
import json
from fastapi import HTTPException
from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import WorkItem, WorkRevision
from sqlalchemy import select


def scope(actor):
    return {'actorId': actor.id, 'companyId': actor.company_id, 'role': actor.role, 'team': False, 'reads': {}}


def role_valid(actor, access):
    return bool(actor) and (not access or not access.get('team') or (actor.active and access.get('actorId') == actor.id and access.get('companyId') == actor.company_id and (not access.get('team') or actor.role == 'admin')))


async def employee(db, actor, identifier):
    if not actor.active or actor.role != 'admin':
        problem(403, '当前账号不能查询团队业务')
    member = await db.scalar(select(Member).where(Member.id == identifier, Member.company_id == actor.company_id, Member.role == 'employee'))
    if not member:
        problem(404, '员工不存在或无权查看')
    return member


async def resolve(db, actor, evidence, *, latest=False, retained=False):
    """Recheck every reference from the database, not from model-supplied claims."""
    if evidence.get('type') == 'own_work':
        work = await db.scalar(select(WorkItem).where(WorkItem.id == evidence['id'], WorkItem.owner_id == actor.id, WorkItem.company_id == actor.company_id, WorkItem.deleted.is_(False)))
        if not work or not role_valid(actor, work.access):
            problem(404, '本人事项已删除或无权查看')
        return work, actor
    member = await employee(db, actor, evidence['ownerId'])
    kind, identifier = evidence['type'], evidence['id']
    model = {'member': Member, 'work': WorkItem, 'report': Report, 'message': Message, 'document': Attachment}.get(kind)
    if not model:
        problem(404, '来源不存在或无权查看')
    if kind == 'member':
        return member, member
    if retained:
        return None, member
    item = await db.scalar(select(model).where(model.id == identifier, model.company_id == actor.company_id, model.owner_id == member.id))
    if not item or item.deleted:
        problem(404, '来源已删除或无权查看')
    if kind == 'work':
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.id == evidence.get('versionId'), WorkRevision.work_id == item.id, WorkRevision.owner_id == member.id, WorkRevision.company_id == actor.company_id))
        if not revision or revision.access.get('team'):
            problem(404, '工作修订不存在或无权查看')
        if latest and item.revision != revision.revision:
            problem(409, '关联工作已更新，请重新查询后生成建议', 'source_changed')
        return revision, member
    if kind == 'report':
        revision = await db.scalar(select(ReportRevision).where(ReportRevision.id == evidence.get('versionId'), ReportRevision.report_id == item.id, ReportRevision.owner_id == member.id, ReportRevision.company_id == actor.company_id))
        if not revision or revision.revision > item.published_revision:
            problem(404, '报告版本尚未提交或已删除')
        if latest and item.published_revision != revision.revision:
            problem(409, '关联报告已重新提交，请重新查询后生成建议', 'source_changed')
        return revision, member
    parent = evidence.get('parent')
    if not isinstance(parent, dict) or parent.get('ownerId') != member.id or parent.get('type') not in ('work', 'report', 'message'):
        problem(404, '来源没有可访问的业务关联')
    record, _ = await resolve(db, actor, parent, latest=latest)
    if kind == 'message':
        if parent['type'] == 'work':
            source_ids = record.source_ids
        elif parent['type'] == 'report':
            revisions = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(record.source_ids), WorkRevision.owner_id == member.id, WorkRevision.company_id == actor.company_id))).all()
            source_ids = [mid for r in revisions for mid in r.source_ids]
        else:
            problem(404, '消息没有可访问的业务关联')
        if item.id not in source_ids:
            problem(404, '消息不属于所引用业务')
        if latest and item.transcript_revision != evidence.get('version'):
            problem(409, '关联语音文字已更新，请重新查询', 'source_changed')
    elif kind == 'document':
        if parent['type'] != 'message' or item.message_id != record.id or item.kind != 'document':
            problem(404, '文件不属于所引用消息')
        if item.extraction_revision != evidence.get('version'):
            problem(409, '文件提取版本已变化，请重新查询', 'source_changed')
    return item, member


async def valid(db, actor, access, *, latest=False, retained=False):
    if not role_valid(actor, access):
        return False
    if not access or not access.get('team'):
        return True
    if access.get('invalidated') and not retained:
        return False
    try:
        for evidence in access.get('reads', {}).values():
            await resolve(db, actor, evidence, latest=latest, retained=retained)
    except (HTTPException, KeyError, TypeError, RecursionError):
        return False
    return True


async def require(db, actor, access, *, latest=False, retained=False):
    if not await valid(db, actor, access, latest=latest, retained=retained):
        problem(409 if latest else 403, '关联资料已变化或无权查看，请重新查询；旧内容不会继续使用', 'business_access_changed')


def merge_access(base, inherited):
    if not inherited or not inherited.get('team'):
        return base
    reads = {**base.get('reads', {}), **inherited.get('reads', {})}
    if len(reads) > 500:
        problem(422, '本次引用范围过大，请缩小查询范围')
    return {**inherited, **base, 'team': True, 'reads': reads, **({'invalidated': True} if base.get('invalidated') or inherited.get('invalidated') else {})}


def merge_links(*groups):
    """Keep server-verified associations when an edit changes the target/source."""
    links = {link['token']: link for group in groups for link in group or []}
    if len(links) > 500:
        problem(422, '本次引用范围过大，请缩小查询范围')
    return list(links.values())


def inherit(actor, target, *sources, include_message_links=False):
    """An ordinary edit cannot remove the restrictions of content it reuses.

    Callers authorize sources before calling this function. Retention after a
    source deletion remains a read rule for confirmed work, not a way to clear
    the provenance on a new draft or revision.
    """
    access = target.access or scope(actor)
    links = getattr(target, 'business_links', [])
    for source in sources:
        access = merge_access(access, source.access)
        source_links = getattr(source, 'business_links', [])
        if include_message_links and isinstance(source, Message):
            source_links = [{'token': token, 'evidence': evidence} for token, evidence in source.access.get('reads', {}).items() if evidence.get('type') in ('work', 'report')]
        links = merge_links(links, source_links)
    target.access = access
    if hasattr(target, 'business_links'):
        target.business_links = links


def receipt(kind, record, *, version=None, parent=None, ordinal=None):
    item = {'type': kind, 'id': record.work_id if kind == 'work' else record.report_id if kind == 'report' else record.id, 'ownerId': record.owner_id if kind != 'member' else record.id}
    if kind in ('work', 'report'):
        item.update(versionId=record.id, version=record.revision)
    elif version is not None:
        item['version'] = version
    if parent:
        item['parent'] = parent
    if ordinal is not None:
        item['ordinal'] = ordinal
    return item


def remember(job, actor, evidence):
    token = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()[:24]
    job.access = merge_access(job.access or scope(actor), {'team': True, 'reads': {token: evidence}})
    return token
