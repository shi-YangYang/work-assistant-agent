"""Remove retired private files; preserve published versions of active conversations."""
import time
from sqlalchemy import select
from app.modules.conversations.models import Conversation
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.members.models import Member
from app.modules.executions.models import SandboxExecution
from app.tasks.models import Job


async def clean_files(db, settings):
    rows = (await db.execute(select(DeliverableRevision, Conversation.deleted, Member.deleted).join(Deliverable, Deliverable.id == DeliverableRevision.deliverable_id)
        .join(Conversation, Conversation.id == Deliverable.conversation_id).join(Member, Member.id == Deliverable.owner_id))).all()
    retained = set()
    for record, conversation_deleted, member_deleted in rows:
        if conversation_deleted or member_deleted:
            record.files = []
        else:
            retained.update(file['storageKey'] for file in record.files or [])
    root = settings.media_dir / 'generated'
    if root.exists():
        for path in root.iterdir():
            # A failed publication leaves a temporary orphan. Grace allows other
            # transactions to commit without deleting files being published now.
            if path.is_file() and path.name not in retained and time.time() - path.stat().st_mtime > 3600:
                path.unlink(missing_ok=True)


async def stop_retired(sessions, settings):
    if not settings.sandbox_url or not settings.sandbox_token:
        return
    from app.integrations.sandbox.client import SandboxClient
    client = SandboxClient(settings)
    async with sessions() as db:
        rows = (await db.execute(select(SandboxExecution.key).join(Job, Job.id == SandboxExecution.job_id).where(
            SandboxExecution.state.in_(('queued', 'running')), Job.state != 'running').limit(32))).scalars().all()
    for key in rows:
        await client.best_effort('release', key)
        async with sessions.begin() as db:
            row = await db.scalar(select(SandboxExecution).where(SandboxExecution.key == key).with_for_update())
            if row and row.state in ('queued', 'running'):
                row.state = 'cancelled'
                row.code = ''
                row.result = {'state': 'cancelled', 'message': '原任务已停止'}
