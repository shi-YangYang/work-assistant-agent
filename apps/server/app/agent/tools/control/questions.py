import json
from fastapi import HTTPException
from app.agent.tool_results import http_failure
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.interactions.schemas import Question


@tool
async def request_user_input(questions: list[Question], runtime: ToolRuntime[RunContext], continue_task: bool = False) -> str:
    """Show 1-3 clarification questions and wait for the actual user's answer.

    Unclear operation/scope: ask text or ordinary single/multiple options directly,
    without loading tools or querying first. Ordinary options use IDs/labels;
    allowCustom accepts other answers. Only actual object options need already
    read objectType/objectId; server resolves labels. Approval uses its own cards.
    Actual answers resume without replaying completed steps. continue_task=true
    if this input answers the prior task but leaves a gap; false for a new task.
    """
    from app.agent.actions.interactions import ask
    try:
        return json.dumps(await ask(runtime.context, [q.model_dump() for q in questions], continue_task=continue_task), ensure_ascii=False)
    except HTTPException as error:
        return json.dumps(http_failure(error), ensure_ascii=False)
    except ValueError:
        return json.dumps({'state': 'failed', 'category': 'invalid_arguments', 'message': '提问格式无效，请修正后再调用'}, ensure_ascii=False)
