"""Task-scoped capability discovery; visibility never grants data access."""
import json
import time
from typing import Annotated
from langchain.tools import ToolRuntime, tool
from pydantic import Field
from app.agent.prompts.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES, EXECUTION_TOOLS
from app.core.digests import digest
from app.tasks.context import BudgetExceeded, RunContext
from app.tasks.lease import lease

GROUPS = {
    'work': frozenset({'find_work_items', 'get_work_item', 'list_work_updates', 'list_work_materials', 'read_work_material', 'propose_progress', 'execute_business_action', 'get_business_actions', *TEAM_TOOL_NAMES}),
    'reports': frozenset({'query_reports', 'query_report_obligations', 'execute_business_action', 'get_business_actions', 'query_team_business', 'read_team_source'}),
    'research': frozenset({'web_search', 'web_fetch'}),
    'documents': frozenset({'find_documents', 'read_document', 'get_message_context', 'read_file', 'save_deliverable', 'read_deliverable'}),
    'files': EXECUTION_TOOLS | frozenset({'read_execution', 'read_deliverable'}),
    'memory': frozenset({'save_memory', 'forget_memory'}),
    'task_context': frozenset({'set_task_context', 'request_user_input'}),
}
DESCRIPTIONS = {
    'work': '查询和修改本人工作、进展、材料',
    'reports': '查询本人报告/待办，生成、编辑和提交报告',
    'research': '搜索和读取公开网页',
    'documents': '读取私人附件/历史消息，保存与修改私人方案、文稿、清单及稳定条目',
    'files': '表格检查、文件/图表/文档生成、Python计算及执行记录',
    'memory': '保存或忘记用户直接自述的稳定个人背景',
    'task_context': '集中澄清，记录持续指令变更、承接任务与未完成项',
}
RECEIPT_GROUPS = {
    'create_work': 'work', 'update_work': 'work', 'delete_work': 'work',
    'generate_report': 'reports', 'edit_report': 'reports', 'submit_report': 'reports', 'delete_report': 'reports',
}


def allowed_tools(context):
    allowed = ALLOWED_TOOLS | (TEAM_TOOL_NAMES if context.role == 'admin' else frozenset())
    if not sandbox_enabled(context):
        allowed -= EXECUTION_TOOLS
    return allowed


def sandbox_enabled(context):
    return bool(getattr(context.settings, 'sandbox_url', '') and getattr(context.settings, 'sandbox_token', ''))


def available_groups(context):
    allowed = allowed_tools(context)
    groups = {name: tools & allowed for name, tools in GROUPS.items() if name != 'files' or sandbox_enabled(context)}
    if 'files' not in groups:
        groups['documents'] |= {'read_execution'}
    return groups


def scope_key(context):
    # Retry fences change without changing the input. New data/config/input scopes
    # must not inherit discovery; identities also prevent copied state leaking.
    return digest({'company': context.company_id, 'owner': context.owner_id, 'job': context.job_id,
                   'scope': context.node_scope, 'input': context.source_revision,
                   'documents': context.document_snapshot, 'work': context.work_reference_snapshot,
                   'config': context.model_binding, 'configAttempt': context.config_attempt})


def previous_receipt_groups(context):
    # Private source stamps identify the exact preceding turn and its own
    # committed/accepted receipts. Revalidated history supplies visible states.
    # Neither prose, inherited receipt links nor older business turns are seeds.
    previous = context.context_sources.get('previousMessageId')
    direct = set(context.context_sources.get('sources', {}).get(previous, {}).get('toolReceiptIds', ()))
    reference = next((item for item in context.conversation_references or [] if item['id'] == previous), {})
    return {RECEIPT_GROUPS[card['action']] for card in reference.get('currentActions', [])
            if card.get('id') in direct and card.get('state') in ('succeeded', 'running')
            and card.get('action') in RECEIPT_GROUPS}


def loaded_groups(context, job):
    saved = job.result.get('toolCatalog', {})
    saved_groups = saved.get('groups', []) if saved.get('scope') == scope_key(context) else []
    # Current UI inputs and revalidated adjacent receipts prepare schemas only.
    # They grant no access or write authority; all original tools still check
    # live identity, ownership, source versions and operation intent.
    seeded = previous_receipt_groups(context)
    if context.work_reference_snapshot and not context.work_reference_snapshot.get('unavailable'):
        seeded.add('work')
    if context.current_document_ids:
        seeded.add('documents')
    available = available_groups(context)
    return [group for group in available if group in saved_groups or group in seeded]


def remember_groups(context, job, groups):
    loaded = set(loaded_groups(context, job)) | set(groups)
    value = {'scope': scope_key(context), 'groups': [group for group in available_groups(context) if group in loaded]}
    if job.result.get('toolCatalog') != value:
        job.result = {**job.result, 'toolCatalog': value}
    return value['groups']


def remember_legacy_call(context, job, call):
    """Old checkpoints still execute through all original authorization checks."""
    name = call['name']
    loaded = loaded_groups(context, job)
    available = available_groups(context)
    if any(name in available[group] for group in loaded):
        return
    candidates = [group for group, names in available.items() if name in names]
    if not candidates:
        return
    preferred = 'reports' if call.get('args', {}).get('action', '').endswith('_report') else candidates[0]
    remember_groups(context, job, [preferred if preferred in candidates else candidates[0]])


def catalog_schema(context):
    descriptions = dict(DESCRIPTIONS)
    if context.role == 'admin':
        descriptions['work'] += '；查询员工已授权业务，关联本人督办'
        descriptions['reports'] = '查询员工已提交报告/汇报待办，准备报告删除；不能写本人或员工报告'
    available = available_groups(context)
    # read_execution remains usable for past receipts even with sandbox disabled.
    if 'files' not in available:
        descriptions['documents'] += '；读取已有执行记录'
    return {'type': 'function', 'function': {
        'name': 'load_tools',
        'description': '按需加载能力的工具定义与规则；不读取资料或授权写入。普通回答无需调用。可一次选择多个相关组：' + '；'.join(f'{name}：{descriptions[name]}' for name in available),
        'parameters': {'type': 'object', 'properties': {'groups': {'type': 'array', 'items': {'type': 'string', 'enum': list(available)}, 'minItems': 1, 'maxItems': len(GROUPS)}}, 'required': ['groups'], 'additionalProperties': False},
    }}


def visible_tools(context, groups):
    available = available_groups(context)
    names = {'load_tools'}
    for group in groups:
        names.update(available.get(group, ()))
    return names


@tool
async def load_tools(groups: Annotated[list[str], Field(min_length=1, max_length=7)], runtime: ToolRuntime[RunContext]) -> str:
    """Load named capabilities for this task; does not read data or grant access."""
    context = runtime.context
    if (time.time() >= context.node_deadline if context.node_retry else time.monotonic() - context.started > 180):
        from app.tasks.budget.state import TaskBudgetStopped
        raise TaskBudgetStopped('time')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        available = available_groups(context)
        if any(group not in available for group in groups):
            return json.dumps({'state': 'unavailable', 'available': list(available)}, ensure_ascii=False)
        loaded = remember_groups(context, job, groups)
        return json.dumps({'state': 'loaded', 'groups': loaded, 'tools': sorted(visible_tools(context, loaded) - {'load_tools'})}, ensure_ascii=False)


if set().union(*GROUPS.values()) != (ALLOWED_TOOLS | TEAM_TOOL_NAMES) - {'finish_task'}:
    raise RuntimeError('Capability catalog does not cover the registered tools')
