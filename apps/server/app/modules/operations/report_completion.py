"""Complete approved report handoffs in a write transaction, never a GET."""
from fastapi import HTTPException
from sqlalchemy import select
from app.db.base import now
from app.modules.operations.models import BusinessAction
from app.modules.operations.execution_policy import effective, decide
from app.modules.operations.receipts import refresh_generation
from app.modules.operations.targets import source_check
from app.modules.reports.service import submit_report


async def submit_action(db, actor, row):
    item = await submit_report(db, actor, row.params['targetId'], row.params['expectedRevision'])
    row.result = {'objectType': 'report', 'objectId': item.id, 'revision': item.revision}
    row.state, row.params, row.updated_at = 'succeeded', {}, now()


async def complete_action(db, actor, row):
    await refresh_generation(db, actor, row)
    if row.action != 'submit_report' or row.state != 'pending':
        return
    from app.modules.conversations.models import Conversation
    conversation = await db.get(Conversation, row.conversation_id) if row.conversation_id else None
    mode = effective(row.execution_mode, conversation.execution_mode if conversation else 'auto')
    if decide(mode, 'submit_report', explicitly_confirm=row.params.get('explicitConfirmation', False)).outcome != 'allow':
        return
    try:
        async with db.begin_nested():
            await source_check(db, actor, row)
            await submit_action(db, actor, row)
            row.revision += 1
    except HTTPException as error:
        row.state = 'conflict'
        row.result = {**row.result, 'message': error.detail['message']}


async def complete_report(db, actor, job):
    rows = (await db.scalars(select(BusinessAction).where(BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id, BusinessAction.action == 'generate_report', BusinessAction.state == 'running', BusinessAction.result['jobId'].astext == job.id).with_for_update())).all()
    for row in rows:
        await complete_action(db, actor, row)
