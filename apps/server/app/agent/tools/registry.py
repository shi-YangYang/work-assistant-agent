from app.agent.tools.catalog import load_tools
from app.agent.tools.resources.images import generate_image
from app.agent.tools.resources.image_reads import read_images
from app.agent.tools.memory import MEMORY_TOOLS
from app.agent.tools.sandbox import SANDBOX_TOOLS
from app.agent.tools.sandbox.execution import run_python, read_execution
from app.agent.tools.control.completion import finish_task
from app.agent.tools.control.task_context import set_task_context
from app.agent.tools.control.questions import request_user_input
from app.agent.tools.business.actions import ACTION_TOOLS
from app.agent.prompts.policies import ALLOWED_TOOLS
from app.agent.tools.resources.documents import find_documents
from app.agent.tools.business.work import find_work_items
from app.agent.tools.resources.messages import get_message_context
from app.agent.tools.business.work import get_work_item
from app.agent.tools.business.work_records import WORK_RECORD_TOOLS
from app.agent.tools.business.work import propose_progress
from app.agent.tools.resources.documents import read_document
from app.agent.tools.resources.deliverables import DELIVERABLE_TOOLS
from app.agent.tools.resources.web import WEB_TOOLS


BUSINESS_TOOLS = [load_tools, generate_image, read_images, *MEMORY_TOOLS, *WORK_RECORD_TOOLS, *SANDBOX_TOOLS, run_python, read_execution, finish_task, set_task_context, request_user_input, *ACTION_TOOLS, *DELIVERABLE_TOOLS, *WEB_TOOLS, find_work_items, get_work_item, get_message_context, propose_progress, find_documents, read_document]


if {tool.name for tool in BUSINESS_TOOLS} != (ALLOWED_TOOLS - {'read_file'}) | {'load_tools'}:
    raise RuntimeError('Business tool registry does not match its allowlist')
