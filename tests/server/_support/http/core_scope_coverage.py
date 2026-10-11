"""Shared controlled fixtures extracted from test_core_scope_coverage."""
import json
from sqlalchemy import select
from app.db.idempotency import Idempotency
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import Conversation
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.interactions.models import AssistantInteraction
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import ProgressDraft, WorkItem, WorkRevision
from app.tasks.models import Job


async def snapshot(sessions, companies):
    models = (Conversation, Message, Job, ProgressDraft, WorkItem, WorkRevision, Report, ReportRevision,
              Attachment, AssistantInteraction, Deliverable, DeliverableRevision, Idempotency)
    async with sessions() as db:
        result = {}
        for model in models:
            rows = (await db.scalars(select(model).where(model.company_id.in_(companies)).order_by(model.id))).all()
            result[model.__name__] = [{column.name: getattr(row, column.name) for column in model.__table__.columns} for row in rows]
        return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
