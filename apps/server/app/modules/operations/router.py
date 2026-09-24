from .commands import confirm_business_action_command
from fastapi import APIRouter
from app.core.schemas import Revision
from app.http.dependencies import AUTH, DB, SETTINGS
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.operations.receipts import action_dto as actions_action_dto
from app.security.ownership import owned
from sqlalchemy import exists, select

router = APIRouter()


@router.get('/api/v1/business-actions')
async def business_actions(conversationId: str, orphanOnly: bool = False, actor=AUTH, db=DB):
    await owned(db, Conversation, conversationId, actor)
    query = select(BusinessAction).where(BusinessAction.company_id == actor.company_id, BusinessAction.owner_id == actor.id, BusinessAction.conversation_id == conversationId)
    if orphanOnly:
        query = query.where(~exists(select(Message.id).where(Message.id == BusinessAction.message_id, Message.deleted.is_(False))))
    rows = (await db.scalars(query.order_by(BusinessAction.created_at.desc()).limit(80))).all()
    return {'items': [await actions_action_dto(db, actor, row) for row in rows]}


@router.post('/api/v1/business-actions/{identifier}/{choice}')
async def confirm_business_action(identifier: str, choice: str, body: Revision, actor=AUTH, db=DB, settings=SETTINGS):
    return await confirm_business_action_command(identifier, choice, body, actor, db, settings)
