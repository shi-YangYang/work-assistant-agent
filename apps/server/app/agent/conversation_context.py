from app.modules.conversations.references import message_reference, request_text


async def conversation_references(db, actor, job, current, budget=None, *, context=None):
    from app.modules.conversations.context_store import references, capture_sources
    if context is not None and context.conversation_references is not None:
        return context.conversation_references
    selected = await references(db, actor, job, current)
    if context is not None:
        context.conversation_references = selected
        context.context_sources = await capture_sources(db, actor, current, selected)
    return selected
