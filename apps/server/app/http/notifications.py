from fastapi import APIRouter
from app.http.dependencies import READ_AUTH, DB
from app.modules.announcements.service import unread_count as announcement_unread
from app.modules.reports.scheduling.notifications import unread_count as reminder_unread

router = APIRouter()


@router.get('/api/v1/notification-summary')
async def summary(actor=READ_AUTH, db=DB):
    reminders = await reminder_unread(db, actor)
    announcements = await announcement_unread(db, actor)
    return {'remindersUnread': reminders, 'announcementsUnread': announcements,
            'totalUnread': reminders + announcements}
