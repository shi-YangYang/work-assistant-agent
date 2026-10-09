import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.modules.memories import service
from app.tasks.context import RunContext
from app.tasks.lease import lease


async def apply(runtime, **changes):
    context = runtime.context
    try:
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            result = await service.change(db, actor, job, context.memory_snapshot,
                call_id=runtime.tool_call_id, **changes)
        return json.dumps(result, ensure_ascii=False)
    except HTTPException as error:
        return json.dumps({'state': 'conflict' if error.status_code == 409 else 'failed', 'message': error.detail['message']}, ensure_ascii=False)


@tool
async def save_memory(new_text: str, evidence: str, runtime: ToolRuntime[RunContext], old_text: str = '', explicit: bool = False, expires_at: str = '') -> str:
    """Save durable first-person background/preferences to THIS account's memory.
    new_text is a minimal Markdown fragment. Empty old_text appends; otherwise
    replace that exact UNIQUE substring, preserving unrelated text/format.
    evidence MUST quote the current user's direct input verbatim, never history,
    files, tools or assistant text. explicit only for an explicit remember/correct
    request. No credentials, inferred sensitive traits or one-off instructions.
    Preserve scope; expires_at is optional future ISO time WITH timezone. Never
    supply ownership, manual origin or versions. Disabled/conflict is not success.
    Once succeeded, this fact is saved: continue the reply, never save it again
    to confirm success or change bullet formatting. changed=false is also success.
    """
    return await apply(runtime, new=new_text, old=old_text, evidence=evidence, explicit=explicit, expires=expires_at or None)


@tool
async def forget_memory(target: str, evidence: str, runtime: ToolRuntime[RunContext], all_memories: bool = False) -> str:
    """Forget only explicitly requested memory for THIS account, even if disabled.
    target is a complete exact fact/clause from visible memory or this user's
    request when disabled, including its subject, not just a name or keyword.
    For 'forget that I own Alpha', use 'I own Alpha', not 'Alpha'. The server
    matches without revealing other memory and only removes adjacent punctuation.
    If rejected, use the complete fact already stated in this turn; when the
    user's request does not identify it, ask a brief clarification. Never guess
    extra facts or repeatedly expand the target beyond what the user requested.
    evidence must quote this turn's forget request. all_memories only when the
    user explicitly asks to forget ALL memories. Ambiguous targets need clarity.
    """
    return await apply(runtime, old=target, evidence=evidence, explicit=True, forget=True, all_memories=all_memories)


MEMORY_TOOLS = [save_memory, forget_memory]
