import asyncio
from datetime import timedelta
from app.db.base import now
from app.modules.attachments.lifecycle import retire_expired_uploads
from app.modules.auth.models import LoginAttempt, Session
from app.tasks.processing.handlers import log
from app.tasks.models import Job
from app.tasks.maintenance.scheduling import schedule_once
from sqlalchemy import delete, update


async def maintenance(sessions, settings):
    from app.modules.operations.mutations.deletion import clean_files
    from app.modules.voiceprints.cleanup import drain
    await drain(sessions, settings)
    from app.modules.executions.cleanup import stop_retired, clean_files as clean_generated_files
    await stop_retired(sessions, settings)
    # Do not acquire company locks after another cleanup's attachment writes
    # have autoflushed. Commit retirement before any physical file cleanup.
    async with sessions.begin() as db:
        await retire_expired_uploads(db, now() - timedelta(hours=24))

    async with sessions.begin() as db:
        from app.modules.work.materials.cleanup import retire_orphans
        await retire_orphans(db)
        await clean_generated_files(db, settings)
        await db.execute(update(Job).where(Job.state.in_(('succeeded', 'awaiting_input', 'failed', 'awaiting_retry', 'cancelled')), Job.updated_at < now() - timedelta(days=1), Job.feedback != {}).values(feedback={}))
        await db.execute(delete(Session).where(Session.expires_at < now()))
        await db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now() - timedelta(minutes=10)))

    async with sessions.begin() as db:
        await clean_files(db, settings)


async def scheduler(sessions, settings):
    while True:
        try:
            await schedule_once(sessions)
            await maintenance(sessions, settings)
        except Exception as error:
            log.warning('scheduler failure_type=%s', type(error).__name__)
        await asyncio.sleep(60)
