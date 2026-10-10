from sqlalchemy import select
from app.core.errors import problem
from app.modules.work.models import WorkItem, WorkRevision, WorkMaterial
from app.security.ownership import owned
from app.security.access import require, inherit


async def readable_work(db, actor, identifier, *, revision=None):
    work = await owned(db, WorkItem, identifier, actor, read=True)
    await require(db, actor, work.access, retained=True)
    if revision is not None:
        selected = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id, WorkRevision.revision == revision))
        if not selected:
            problem(404, '工作修订不存在')
        await require(db, actor, selected.access, retained=True)
    return work


async def historical_materials(db, work, revision):
    selected = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id, WorkRevision.revision == revision))
    return selected.content.get('materialIds', [])


async def require_agent_work(db, actor, job, work):
    if work.owner_id != actor.id:
        from app.security.access import resolve
        evidence = next((item for item in job.access.get('reads', {}).values() if item.get('type') == 'work' and item.get('id') == work.id and item.get('version') == work.revision), None)
        if not evidence:
            problem(404, '请先通过团队查询读取该工作的最新业务来源')
        await resolve(db, actor, evidence, latest=True)
    inherit(actor, job, work)


async def work_for_material(db, actor, attachment_id, *, current=True, work_revision=None):
    row = await db.scalar(select(WorkMaterial).where(WorkMaterial.attachment_id == attachment_id, WorkMaterial.company_id == actor.company_id))
    if not row:
        return None
    work = await owned(db, WorkItem, row.work_id, actor, read=True)
    await require(db, actor, work.access, retained=True)
    if work_revision is not None:
        await readable_work(db, actor, work.id, revision=work_revision)
        if row.id not in await historical_materials(db, work, work_revision):
            problem(404, '该版本不包含此材料')
    if current and row.removed and work_revision is None:
        problem(404, '工作材料已移除')
    return work

