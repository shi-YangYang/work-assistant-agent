from paa_server.modules.members.models import Member
from paa_server.modules.messages.models import Message
from paa_server.modules.work.models import ProgressDraft
from paa_server.security.access import valid
from paa_server.tasks.models import Job
from sqlalchemy import select, text


async def invalidate_deleted(db, company_id):
    """Invalidate all dependent owners while the caller holds the company lock."""
    jobs = (await db.scalars(select(Job).where(Job.company_id == company_id, Job.access['team'].as_boolean().is_(True)).with_for_update())).all()
    for job in jobs:
        actor = await db.get(Member, job.owner_id)
        if actor and await valid(db, actor, job.access):
            continue
        job.access = {**job.access, 'invalidated': True}
        if job.state in ('queued', 'running', 'failed', 'awaiting_retry'):
            job.state, job.phase, job.error, job.lease_until = 'cancelled', 'business_access_changed', '关联资料已删除或权限已变化，请重新提问', None
            job.fence += 1
        job.result = {}
        for table in ('checkpoint_writes', 'checkpoint_blobs', 'checkpoints'):
            if await db.scalar(text('SELECT to_regclass(:table)'), {'table': table}):
                await db.execute(text(f'DELETE FROM {table} WHERE thread_id LIKE :prefix'), {'prefix': f'{company_id}:{job.owner_id}:job:{job.id}%'})
    messages = (await db.scalars(select(Message).where(Message.company_id == company_id, Message.access['team'].as_boolean().is_(True)))).all()
    for message in messages:
        actor = await db.get(Member, message.owner_id)
        if actor and await valid(db, actor, message.access):
            continue
        message.reply, message.citations, message.suggestions = '', [], []
        message.access = {**message.access, 'invalidated': True}
        for draft in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == message.id, ProgressDraft.status == 'pending'))).all():
            draft.status, draft.content = 'deleted', {}
            draft.revision += 1
