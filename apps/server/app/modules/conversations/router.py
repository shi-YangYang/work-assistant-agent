from .queries import conversations_query
from fastapi import APIRouter, Query
from app.core.errors import problem
from app.core.schemas import Revision
from app.core.versions import version
from app.http.dependencies import AUTH, DB, SETTINGS
from app.modules.conversations.models import Conversation
from app.modules.conversations.schemas import ConversationCreate, ConversationEdit
from app.modules.conversations.serializers import conversation_dto
from app.security.ownership import owned
from app.tasks.cleanup import finish_deletion

router = APIRouter()


@router.get('/api/v1/conversations')
async def conversations(q: str = Query('', max_length=120), cursor: str | None = None, actor=AUTH, db=DB):
    return await conversations_query(q, cursor, actor, db)


@router.post('/api/v1/conversations', status_code=201)
async def add_conversation(body: ConversationCreate, actor=AUTH, db=DB):
    if not body.title.strip():
        problem(422, '请输入会话名称')
    item = Conversation(company_id=actor.company_id, owner_id=actor.id, title=body.title.strip())
    db.add(item)
    await db.flush()
    return conversation_dto(item)


@router.get('/api/v1/conversations/{identifier}')
async def get_conversation(identifier: str, actor=AUTH, db=DB):
    return conversation_dto(await owned(db, Conversation, identifier, actor))


@router.patch('/api/v1/conversations/{identifier}')
async def rename_conversation(identifier: str, body: ConversationEdit, actor=AUTH, db=DB):
    item = await owned(db, Conversation, identifier, actor, lock=True)
    version(item, body.expectedRevision)
    if not body.title.strip():
        problem(422, '请输入会话名称')
    item.title, item.revision = body.title.strip(), item.revision + 1
    return conversation_dto(item)


@router.get('/api/v1/conversations/{identifier}/deletion')
async def conversation_deletion(identifier: str, actor=AUTH, db=DB):
    from app.modules.operations.deletion import conversation_impact
    item = await owned(db, Conversation, identifier, actor)
    messages, retained = await conversation_impact(db, item)
    return {'messages': len(messages), 'retainedSources': len(retained)}


@router.delete('/api/v1/conversations/{identifier}')
async def delete_conversation(identifier: str, body: Revision, actor=AUTH, db=DB, settings=SETTINGS):
    from app.modules.operations.deletion import target, remove_conversation
    item = await target(db, Conversation, identifier, actor, body.expectedRevision)
    await remove_conversation(db, item)
    return await finish_deletion(db, item.owner_id, settings)
