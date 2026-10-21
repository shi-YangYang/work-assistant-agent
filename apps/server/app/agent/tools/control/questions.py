import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.interactions.schemas import Question


@tool
async def request_user_input(questions: list[Question], runtime: ToolRuntime[RunContext], continue_task: bool = False) -> str:
    """Show 1-3 clarification questions and wait for the actual user's answer.

    Use single, multiple or text type; allowCustom for answers outside options.
    Object options require already read objectType and objectId; the server
    resolves labels. Preference options use IDs and labels without object fields.
    Business approval uses its own cards. Answers resume this task without
    repeating completed steps.
    Set continue_task=true when this input answers the previous task's question
    and you still need other information; false for a genuinely unrelated task.
    """
    from app.agent.actions.interactions import ask
    try:
        return json.dumps(await ask(runtime.context, [q.model_dump() for q in questions], continue_task=continue_task), ensure_ascii=False)
    except (ValueError, HTTPException) as error:
        return json.dumps({'state': 'failed', 'category': 'invalid_arguments', 'message': error.detail['message'] if isinstance(error, HTTPException) else '提问格式无效，请修正后再调用'}, ensure_ascii=False)
