"""Fresh per-run work facts shared by planning, intent and result review."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from app.modules.messages.work_references import require_work
from app.modules.operations.models import BusinessAction
from app.modules.work.projection import work_for_model


async def work_context(db, actor, job, message, context):
    if not message.work_reference:
        return None
    identifier = message.work_reference['workId']
    try:
        item = await require_work(db, actor, identifier)
    except HTTPException:
        # Deletion by this very request may be the requested, successful result.
        # External deletion/revocation still aborts the run instead of retargeting.
        deleted = await db.scalar(select(BusinessAction.id).where(
            BusinessAction.message_id == message.id, BusinessAction.owner_id == actor.id,
            BusinessAction.company_id == actor.company_id, BusinessAction.action == 'delete_work',
            BusinessAction.state == 'succeeded', BusinessAction.result['objectId'].astext == identifier))
        if not deleted:
            raise
        if context.work_reference_snapshot is None:
            context.work_reference_snapshot = {'id': identifier, 'unavailable': True, 'deletedByCurrentTask': True}
        return context.work_reference_snapshot
    if context.work_reference_snapshot is None:
        context.work_reference_snapshot = await work_for_model(db, actor, job, item)
        context.read_versions[item.id] = item.revision
    return context.work_reference_snapshot


def reference_evidence(context):
    value = context.work_reference_snapshot
    return [{'tool': 'work_reference', 'result': json.dumps(value, ensure_ascii=False)}] if value and not value.get('unavailable') else []
