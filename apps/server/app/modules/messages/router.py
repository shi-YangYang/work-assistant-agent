from .commands import correct_transcript, submit_message
from fastapi import APIRouter, Header, Query
from app.http.dependencies import AUTH, DB
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.messages.queries import list_messages
from app.modules.messages.schemas import SendMessage, TranscriptEdit
from app.modules.messages.serializers import message_dto
from app.security.ownership import owned
from typing import Annotated

router = APIRouter()


@router.post('/api/v1/messages', status_code=202)
async def send_message(body: SendMessage, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    return await submit_message(db, actor, body, idempotency_key)


@router.get('/api/v1/messages')
async def messages(conversationId: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=AUTH, db=DB):
    if conversationId:
        await owned(db, Conversation, conversationId, actor)
    return await list_messages(db, actor, actor.id, cursor, limit, conversationId)


@router.get('/api/v1/messages/{identifier}')
async def get_message(identifier: str, actor=AUTH, db=DB):
    return await message_dto(db, await owned(db, Message, identifier, actor, read=True), actor)


@router.patch('/api/v1/messages/{identifier}/transcript')
async def transcript(identifier: str, body: TranscriptEdit, actor=AUTH, db=DB):
    return await correct_transcript(db, actor, identifier, body)
