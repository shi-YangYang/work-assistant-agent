import json
from typing import Annotated, Literal
from fastapi import HTTPException
from app.agent.tool_results import http_failure
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.interactions.schemas import MAX_QUESTIONS, MAX_QUESTION_OPTIONS, Question, QuestionOption
from pydantic import Field, model_validator


class InputQuestion(Question):
    type: Literal['single', 'text'] = Field(default='text', description='single: select one option or write a custom answer; text: write an answer only.')
    options: list[QuestionOption] = Field(default_factory=list, max_length=MAX_QUESTION_OPTIONS,
        description=f'For single, AI supplies 1-{MAX_QUESTION_OPTIONS} mutually exclusive choices with unique option IDs and clear labels; text uses []. Do not add Other: custom input is built in.')
    allowCustom: Literal[True] = Field(default=True, description='Always true: the user may write an answer instead of selecting an option.')

    @model_validator(mode='after')
    def text_has_no_options(self):
        if self.type == 'text' and self.options:
            raise ValueError('纯文字问题不能包含选项；提供选项时请使用 single')
        return self


@tool
async def request_user_input(
    questions: Annotated[list[InputQuestion], Field(min_length=1, max_length=MAX_QUESTIONS,
        description='Missing user decisions, displayed one question per page. Question IDs must be unique within this call.')],
    runtime: ToolRuntime[RunContext],
    continue_task: bool = False,
) -> str:
    """Ask for missing user decisions and wait for the submitted answers.

    AI writes concise prompts and ordinary option labels; no loading or queries
    are needed for unclear intent/scope. Option IDs identify choices, not objects.
    For actual objects, supply already-read objectType/objectId; never invent
    objects. Server verifies access/version and resolves labels. Approval uses
    its own cards. Selection advances locally; only final submission resumes.
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
