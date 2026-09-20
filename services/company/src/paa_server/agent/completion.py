"""Finish operation-only requests from durable receipts, never model prose."""
import json

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

from ..business_actions import action_dto, digest
from ..models import BusinessAction, Message
from ..service import owned
from .conversation_context import request_text


async def receipt_completion(context, messages):
    batch = next((message for message in reversed(messages) if isinstance(message, AIMessage)), None)
    if not batch or len(batch.tool_calls) != 1:
        return False
    call = batch.tool_calls[0]
    if call['name'] != 'execute_business_action':
        return False
    output = next((message for message in reversed(messages) if isinstance(message, ToolMessage) and message.tool_call_id == call['id']), None)
    if not output:
        return False
    try:
        result = json.loads(output.content)
    except (ValueError, TypeError):
        return False
    if not isinstance(result, dict) or result.get('state') not in ('succeeded', 'pending', 'running'):
        return False
    from .harness import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'message' or job.result.get('operationFeedback'):
            return False
        rows = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == job.target_id, BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id).limit(2))).all()
        if len(rows) != 1 or rows[0].id != result.get('id') or not rows[0].result.get('receiptOnly'):
            return False
        message = await owned(db, Message, job.target_id, actor)
        request = digest({'text': request_text(message, job), 'sourceRevision': message.transcript_revision, 'documents': context.document_versions})
        if rows[0].result.get('receiptInput') != request:
            return False
        # Recheck permissions, target versions and confirmation previews. A
        # failed/conflicting result always returns to the normal planner.
        card = await action_dto(db, actor, rows[0])
        if card['state'] not in ('succeeded', 'pending', 'running'):
            return False
        job.result = {**job.result, 'responseMode': 'receipt'}
        return True
