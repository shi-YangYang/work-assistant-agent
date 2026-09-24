from paa_server.modules.attachments.documents import attachment_dto
from paa_server.modules.attachments.models import Attachment
from paa_server.modules.operations.receipts import message_actions as actions_message_actions
from paa_server.modules.team.sources import business_link_dtos
from paa_server.modules.work.models import ProgressDraft
from paa_server.modules.work.serializers import draft_dto
from paa_server.security.access import valid as business_valid
from paa_server.tasks.models import Job
from paa_server.tasks.serializers import job_dto
from sqlalchemy import select


async def message_dto(db, item, actor):
    allowed = await business_valid(db, actor, item.access)
    attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == item.id, Attachment.deleted.is_(False)))).all()
    job = await db.scalar(select(Job).where(Job.target_id == item.id, Job.kind == 'message').order_by(Job.created_at.desc()).limit(1))
    private = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id, ProgressDraft.status != 'deleted').order_by(ProgressDraft.created_at))).all() if actor.id == item.owner_id else []
    statuses = {d.id: d.status for d in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id))).all()}
    return {'id': item.id, 'ownerId': item.owner_id, 'conversationId': item.conversation_id, 'text': item.text if allowed else '', 'reply': item.reply if allowed else '', 'businessUnavailable': not allowed, 'citations': [c for c in item.citations if c.get('kind') != 'business'] if allowed else [], 'businessCitations': [c for c in item.citations if c.get('kind') == 'business'] if allowed else [], 'replyTo': item.reply_to, 'transcript': item.transcript if allowed else '', 'transcriptRevision': item.transcript_revision, 'createdAt': item.created_at.isoformat(), 'attachments': [attachment_dto(a) for a in attachments] if allowed else [], 'job': job_dto(job) if job else None, 'drafts': [{**draft_dto(d), 'businessLinks': await business_link_dtos(db, actor, d.business_links)} for d in private if allowed and await business_valid(db, actor, d.access)], 'suggestions': [{**s, 'status': statuses.get(s['id'], 'pending')} for s in item.suggestions] if allowed else [], 'actions': await actions_message_actions(db, actor, item)}
