"""Serialize published storage reservations across tenants sharing one media root."""
from sqlalchemy import select, text
from app.core.errors import problem
from app.modules.deliverables.models import DeliverableRevision


async def reserve(db, settings, actor, incoming_bytes):
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('noria:generated-storage', 0))"))
    revisions = (await db.scalars(select(DeliverableRevision.files).where(DeliverableRevision.owner_id == actor.id))).all()
    used = {item['storageKey']: item['size'] for files in revisions for item in files or []}
    if sum(used.values()) + incoming_bytes > settings.generated_quota_mb * 1024 * 1024:
        problem(422, '成果文件存储额度已满，请删除不需要的会话后重试')
    root = settings.media_dir / 'generated'
    # Count pending/orphan bytes too; repeated cancelled publications must not
    # evade the server-wide limit while awaiting periodic cleanup.
    physical = sum(path.stat().st_size for path in root.iterdir() if path.is_file()) if root.exists() else 0
    if physical + incoming_bytes > settings.generated_total_quota_mb * 1024 * 1024:
        problem(422, '文件存储空间已满，请联系管理员清理或扩容')
