from app.modules.attachments.documents import attachment_dto
from app.modules.attachments.models import Attachment
from app.modules.operations.receipts import message_actions as actions_message_actions, current_reply
from app.modules.team.sources import business_link_dtos
from app.modules.work.models import ProgressDraft
from app.modules.work.serializers import draft_dto
from app.modules.messages.references.web_sources import web_source_dtos
from app.security.access import valid as business_valid
from app.tasks.models import Job
from app.tasks.serializers import job_dto
from sqlalchemy import select


async def message_dto(db, item, actor):
    allowed = await business_valid(db, actor, item.access)
    attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == item.id, Attachment.deleted.is_(False)))).all()
    job = await db.scalar(select(Job).where(Job.target_id == item.id, Job.kind == 'message').order_by(Job.created_at.desc()).limit(1))
    order = {identifier: index for index, identifier in enumerate((job.result or {}).get('attachmentOrder', []))} if job else {}
    attachments = sorted(attachments, key=lambda attachment: (order.get(attachment.id, len(order)), attachment.created_at, attachment.id))
    cards = await actions_message_actions(db, actor, item)
    from app.modules.work.drafts.draft_receipts import message_drafts
    visible_drafts = await message_drafts(db, actor, item, job)
    outcome_allowed = allowed and actor.id == item.owner_id and job and (not job.access or job.access.get('role') == actor.role) and await business_valid(db, actor, job.access)
    if outcome_allowed:
        from app.tasks.feedback.outcomes import refresh
        refresh(job, cards, visible_drafts)
    job_value = job_dto(job) if job else None
    if job_value and not outcome_allowed:
        job_value['taskOutcome'] = None
    statuses = {d.id: d.status for d in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id))).all()}
    from app.modules.deliverables.serializers import message_deliverables
    results = await message_deliverables(db, actor, item) if allowed else []
    from app.modules.interactions.serializers import message_interactions
    interactions = await message_interactions(db, actor, item) if allowed else []
    from app.modules.messages.references.work_references import reference_dto
    reference = await reference_dto(db, actor, item.work_reference) if allowed else None
    from app.tasks.feedback.reply_stream import dto as reply_dto
    reply_stream = await reply_dto(db, actor, job, item) if outcome_allowed else None
    return {'replyStream': reply_stream, 'workReference': reference, 'interactions': interactions, 'deliverables': results, 'id': item.id, 'ownerId': item.owner_id, 'conversationId': item.conversation_id, 'text': item.text if allowed else '', 'reply': current_reply(item, job, cards, visible_drafts) if allowed else '', 'businessUnavailable': not allowed, 'citations': [c for c in item.citations if c.get('kind') not in ('business', 'web')] if allowed else [], 'webSources': web_source_dtos(item.citations) if allowed else [], 'businessCitations': [c for c in item.citations if c.get('kind') == 'business'] if allowed else [], 'replyTo': item.reply_to, 'transcript': item.transcript if allowed else '', 'transcriptRevision': item.transcript_revision, 'createdAt': item.created_at.isoformat(), 'attachments': [attachment_dto(a) for a in attachments] if allowed else [], 'job': job_value, 'drafts': [{**draft_dto(d), 'businessLinks': await business_link_dtos(db, actor, d.business_links)} for d in visible_drafts], 'suggestions': [{**s, 'status': statuses.get(s['id'], 'pending')} for s in item.suggestions] if allowed else [], 'actions': cards}
