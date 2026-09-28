from sqlalchemy import func, select
from app.modules.members.models import Member
from app.modules.voiceprints.models import Voiceprint, VoiceprintCleanup
from app.modules.voiceprints.service import private_path


def paths(item):
    return set(filter(None, (item.ready_path, item.pending_path)))


async def schedule_paths(db, company_id, member_id, filenames):
    for filename in set(filenames):
        existing = await db.scalar(select(VoiceprintCleanup.id).where(VoiceprintCleanup.path == filename))
        if not existing:
            db.add(VoiceprintCleanup(company_id=company_id, member_id=member_id, path=filename))
    await db.flush()


async def remove_enrollment(db, item):
    if item:
        await schedule_paths(db, item.company_id, item.member_id, paths(item))
        # Removing the row invalidates in-flight extraction's ID/revision guard.
        await db.delete(item)
        await db.flush()


async def member_impact(db, company_id, member_id):
    item = await db.scalar(select(Voiceprint).where(Voiceprint.company_id == company_id, Voiceprint.member_id == member_id))
    return {'voiceprints': int(item is not None), 'recordings': len(paths(item)) if item else 0}


def legacy_query(company_id):
    return select(Voiceprint).join(Member, Member.id == Voiceprint.member_id).where(Voiceprint.company_id == company_id, Member.company_id == company_id, Member.deleted.is_(True))


async def summary(db, company_id):
    items = (await db.execute(legacy_query(company_id).with_only_columns(Voiceprint.member_id, Voiceprint.ready_path, Voiceprint.pending_path))).all()
    pending, failed = (await db.execute(select(func.count(), func.count().filter(VoiceprintCleanup.error != '')).where(VoiceprintCleanup.company_id == company_id))).one()
    return {'legacy': {'members': len(items), 'voiceprints': len(items), 'recordings': len({path for _, ready, pending_path in items for path in (ready, pending_path) if path})}, 'pending': pending, 'failed': failed}


async def schedule_legacy(db, company_id):
    for item in (await db.scalars(legacy_query(company_id).with_for_update())).all():
        await remove_enrollment(db, item)


async def drain(sessions, settings, *, company_id=None):
    """Only committed intents are eligible. Failed paths stay visible/retryable."""
    async with sessions.begin() as db:
        query = select(VoiceprintCleanup).order_by(VoiceprintCleanup.attempts, VoiceprintCleanup.created_at).with_for_update(skip_locked=True)
        if company_id:
            query = query.where(VoiceprintCleanup.company_id == company_id)
        for item in (await db.scalars(query.limit(1000))).all():
            try:
                private_path(settings, item.path).unlink(missing_ok=True)
            except (OSError, ValueError):
                item.attempts += 1
                item.error = '原录音暂未清理完成，将自动重试，也可手动重试'
            else:
                await db.delete(item)
