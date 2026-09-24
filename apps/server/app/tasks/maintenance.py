import asyncio
from datetime import timedelta
from app.db.base import now
from app.integrations.media import remove_media
from app.modules.attachments.models import Attachment
from app.modules.auth.models import LoginAttempt, Session
from app.tasks.handlers import log
from app.tasks.models import Job
from app.tasks.scheduling import schedule_once
from sqlalchemy import delete, select, update


async def maintenance(sessions, settings):
    from app.modules.operations.deletion import clean_files
    async with sessions.begin() as db:
        await clean_files(db, settings)
        old = (await db.scalars(select(Attachment).where(Attachment.message_id.is_(None), Attachment.created_at < now() - timedelta(hours=24)).with_for_update(skip_locked=True))).all()
        for attachment in old:
            remove_media(settings, attachment.id)
            await db.delete(attachment)
        await db.execute(update(Job).where(Job.state.in_(('succeeded', 'awaiting_input', 'failed', 'awaiting_retry', 'cancelled')), Job.updated_at < now() - timedelta(days=1), Job.feedback != {}).values(feedback={}))
        await db.execute(delete(Session).where(Session.expires_at < now()))
        await db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now() - timedelta(minutes=10)))


async def scheduler(sessions, settings):
    while True:
        try:
            await schedule_once(sessions)
            await maintenance(sessions, settings)
        except Exception as error:
            log.warning('scheduler failure_type=%s', type(error).__name__)
        await asyncio.sleep(60)
