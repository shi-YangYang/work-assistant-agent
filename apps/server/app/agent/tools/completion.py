"""A terminal tool: no extra provider request after delivering the answer."""
from langchain.tools import tool
from app.agent.completion.delivery import Delivery
from app.modules.conversations.task.task_schemas import TaskInterpretation


@tool(return_direct=True)
async def finish_task(answer: str, task: TaskInterpretation, business_requested: bool, verification_requested: bool,
                      operation_ids: list[str] | None = None, verification_quote: str = '',
                      response_complete: bool = True, response_issue: str = '') -> str:
    """Deliver the actual answer and task summary, then end this turn.

    Call alone after all tools finished. This tool never writes business data.
    operation_ids are real action receipt IDs, not work IDs. Include every
    requested result in answer; an apology or future promise is not completion.
    Business requests remain business_requested even when execution is missing.
    verification_requested is FALSE for ordinary search/news, requested sources,
    publication dates or accurate summaries. TRUE only to fact-check an existing
    claim/material the user supplied; verification_quote must quote that request.
    """
    return Delivery(answer=answer, task=task, business_requested=business_requested,
                    operation_ids=operation_ids or [], verification_requested=verification_requested, verification_quote=verification_quote,
                    response_complete=response_complete, response_issue=response_issue).model_dump_json()
