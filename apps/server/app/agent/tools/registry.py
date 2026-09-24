from app.agent.tools.actions import ACTION_TOOLS
from app.agent.policies import ALLOWED_TOOLS
from app.agent.tools.reports import draft_report
from app.agent.tools.documents import find_documents
from app.agent.tools.work import find_work_items
from app.agent.tools.messages import get_message_context
from app.agent.tools.work import get_work_item
from app.agent.tools.work import propose_progress
from app.agent.tools.documents import read_document
from langchain.tools import tool


BUSINESS_TOOLS = [*ACTION_TOOLS, find_work_items, get_work_item, get_message_context, propose_progress, draft_report, find_documents, read_document]


if {tool.name for tool in BUSINESS_TOOLS} != ALLOWED_TOOLS - {'read_file'}:
    raise RuntimeError('Business tool registry does not match its allowlist')
