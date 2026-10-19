"""Authoritative message and receipt projection used by conversation consumers."""
from app.modules.messages.input.audio import transcript_groups
from app.tasks.models import Job
from sqlalchemy import select


from app.modules.messages.input.input_text import request_text
from app.modules.attachments.documents import detach_material_coverage


REPORT_RECEIPT_PROJECTION = 1


def action_reference(card):
    result = {key: card[key] for key in ('id', 'action', 'state', 'objectId', 'objectRevision') if key in card}
    if card['action'].endswith('_report'):
        evidence = card.get('reportSnapshot')
        # Keep the already-authorized, bounded receipt, not the mutable report.
        # Explicit null also distinguishes an unavailable/legacy snapshot from
        # an old cached projection which silently discarded the field.
        result['reportSnapshot'] = {**evidence, 'source': 'business_action_receipt'} if evidence else None
    return result


def has_legacy_report_reference(reference):
    return any(card.get('action', '').endswith('_report') and 'reportSnapshot' not in card
               for card in reference.get('currentActions', []))


async def message_reference(db, actor, message, *, job=None, job_loaded=False):
    from app.modules.operations.receipts import message_actions
    if not job_loaded:
        job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    cards = await message_actions(db, actor, message)
    stored = job.result if job else {}
    # Only keep independently checked non-execution prose beside receipts.
    # Legacy replies may claim obsolete pending/success states, so omit those.
    reply = stored.get('conversationReply', '') if cards else message.reply
    return material_scope_reference({
        **({'workReference': {'workId': message.work_reference['workId']}} if message.work_reference else {}),
        'id': message.id, 'userText': request_text(message, job),
        'materialTranscript': transcript_groups(message.transcript, stored)[1],
        'assistantReference': reply,
        'currentActions': [action_reference(card) for card in cards],
    }, stored)



def material_scope_reference(reference, stored=None):
    """Normalize old cached references without rebuilding their source queries."""
    reply, coverage = detach_material_coverage(reference.get('assistantReference', ''), stored)
    historical = reference.get('historicalMaterialCoverage')
    if coverage:
        historical = {'scope': '过去该次回答的材料范围，不表示本次已重新提供原文或页图', 'items': coverage}
    if not historical:
        return reference
    return {**reference, 'assistantReference': reply,
            'historicalMaterialCoverage': {**historical,
                'readSource': {'tool': 'get_message_context', 'message_id': reference['id']}}}
