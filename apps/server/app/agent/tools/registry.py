from app.agent.tools.sandbox import SANDBOX_TOOLS
from app.agent.tools.execution import run_python, read_execution
from app.agent.tools.completion import finish_task
from app.agent.tools.questions import request_user_input
from app.agent.tools.actions import ACTION_TOOLS
from app.agent.prompts.policies import ALLOWED_TOOLS
from app.agent.tools.documents import find_documents
from app.agent.tools.work import find_work_items
from app.agent.tools.messages import get_message_context
from app.agent.tools.work import get_work_item
from app.agent.tools.work import propose_progress
from app.agent.tools.documents import read_document
from app.agent.tools.deliverables import DELIVERABLE_TOOLS
from app.agent.tools.web import WEB_TOOLS


BUSINESS_TOOLS = [*SANDBOX_TOOLS, run_python, read_execution, finish_task, request_user_input, *ACTION_TOOLS, *DELIVERABLE_TOOLS, *WEB_TOOLS, find_work_items, get_work_item, get_message_context, propose_progress, find_documents, read_document]


if {tool.name for tool in BUSINESS_TOOLS} != ALLOWED_TOOLS - {'read_file'}:
    raise RuntimeError('Business tool registry does not match its allowlist')
