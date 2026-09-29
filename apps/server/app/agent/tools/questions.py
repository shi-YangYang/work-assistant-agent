import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.interactions.schemas import Question


@tool
async def request_user_input(questions: list[Question], runtime: ToolRuntime[RunContext], continue_task: bool = False) -> str:
    """Ask 1-3 necessary questions, then stop while waiting for the actual user.

    Use for unresolved targets, required dates or preferences, not authorization
    approval (business actions provide their own approval cards). Support single,
    multiple or text type. Always allowCustom when the user may supply an answer
    absent from your options. Object options MUST use already read objectType and
    objectId; labels are resolved by server. Text preferences use option IDs only.
    Never ask about optional work fields or themes delegated to you to invent.
    The user's answer resumes this same task and saved steps must not repeat.
    Set continue_task=true when this input answers the previous task's question
    and you still need other information; false for a genuinely unrelated task.
    """
    from app.agent.actions.interactions import ask
    try:
        return json.dumps(await ask(runtime.context, [q.model_dump() for q in questions], continue_task=continue_task), ensure_ascii=False)
    except (ValueError, HTTPException) as error:
        return json.dumps({'state': 'failed', 'category': 'invalid_arguments', 'message': error.detail['message'] if isinstance(error, HTTPException) else '提问格式无效，请修正后再调用'}, ensure_ascii=False)
