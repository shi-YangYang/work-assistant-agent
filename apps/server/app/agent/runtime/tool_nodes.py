"""Controlled tool labels and structured outcomes for the assistant UI."""
import json
from langchain_core.messages import ToolMessage
from app.tasks.nodes.node_execution import execute_node
from app.agent.runtime.progress.tools import tool_presentation


# Replay safety is an execution policy, independent of display-label registration.
REPLAYABLE_TOOLS = frozenset({
    'generate_image', 'save_memory', 'forget_memory', 'set_task_context',
    'inspect_table', 'export_table', 'create_chart', 'create_document', 'create_slides',
    'run_python', 'request_user_input', 'find_work_items', 'get_work_item',
    'list_work_updates', 'list_work_materials', 'read_work_material', 'get_message_context', 'get_business_actions', 'query_reports', 'query_report_obligations',
    'find_documents', 'read_document', 'read_file', 'find_team_members', 'query_team_business',
    'read_team_source', 'propose_progress', 'propose_followup', 'save_deliverable',
    'read_deliverable', 'read_execution', 'web_search', 'web_fetch', 'execute_business_action',
})


async def reject_tool_budget(context, call):
    """Keep known unexecuted steps even when the next reply has no metadata."""
    from app.tasks.lease import lease
    from app.tasks.nodes.node_state import execution, save
    label, presentation = tool_presentation(call['name'], call.get('args'))
    subject = presentation.get('subject')
    remaining = label + (f'：{subject}' if subject else '') + '（未执行）'
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        state = execution(job)
        blocked = list(dict.fromkeys([*state.get('budgetBlockedTools', []), remaining]))
        # Keep bounded display summaries, never full tool arguments or outputs.
        if len(blocked) > 16:
            blocked = [*blocked[:15], '其他工具步骤尚未执行']
        state['budgetBlockedTools'] = blocked
        save(job, state)
    return ToolMessage(tool_call_id=call['id'], name=call['name'], content=json.dumps({
        'state': 'unavailable', 'message': '此工具未执行。请用已有结果直接答复并说明未完成范围，不复述内部执行限制。',
    }, ensure_ascii=False))


def outcome(message):
    if not isinstance(message, ToolMessage):
        return 'failed', '工具未返回可用结果'
    try:
        value = json.loads(message.content)
    except (ValueError, TypeError):
        # Legacy free-form refusal strings carry no success proof. They are
        # normal business responses; never identify errors by prose keywords.
        return ('failed', '工具未完成，请查看答复') if message.status == 'error' else ('awaiting_input', '请查看答复并补充信息')
    if isinstance(value, dict):
        state = value.get('state') or value.get('status')
        if value.get('category') in ('invalid_arguments', 'conflict', 'transient_failure'):
            return 'failed', '操作未完成，请查看业务说明'
        if value.get('category') == 'permission_denied':
            return 'failed', '当前权限无法执行'
        if state == 'not_requested':
            return 'cancelled', '本次未要求该操作'
        if 'error' in value or state in ('failed', 'conflict', 'unavailable', 'cancelled', 'unknown', 'retryable'):
            return 'failed', '操作未执行，请查看业务说明'
        if state in ('clarification', 'waiting', 'not_found'):
            return 'awaiting_input', '需要补充信息' if state != 'not_found' else '未找到匹配内容'
        if state == 'pending':
            return 'awaiting_confirmation', ''
    return ('failed', '工具未完成，请查看业务说明') if message.status == 'error' else ('succeeded', '')


async def tool_node(context, request, operation):
    call = request.tool_call
    batch = next((m for m in reversed(request.state.get('messages', [])) if getattr(m, 'tool_calls', None)), None)
    label, presentation = tool_presentation(call['name'], call.get('args'))
    from app.core.digests import digest
    identity = {'input': digest(call.get('args', {})), 'message': getattr(batch, 'id', None), 'call': call['id'], 'name': call['name']}
    refreshing_work = call['name'] == 'get_work_item' and call.get('args', {}).get('work_id') in context.refresh_work_versions
    if refreshing_work:
        identity['refreshWorkVersions'] = dict(context.refresh_work_versions)
    async def restore_receipt(db, actor, value):
        from app.modules.operations.models import BusinessAction
        from app.modules.operations.receipts import action_dto
        from app.security.ownership import owned
        result = json.loads(value['content'])
        if isinstance(result, dict) and result.get('id'):
            row = await owned(db, BusinessAction, result['id'], actor)
            return {**value, 'content': json.dumps(await action_dto(db, actor, row), ensure_ascii=False)}
        return value
    async def restore_memory(db, actor, value):
        from app.modules.memories.service import restore
        from app.tasks.models import Job
        job = await db.get(Job, context.job_id)
        result = await restore(db, actor, json.loads(value['content']), job=job)
        return {**value, 'content': json.dumps(result, ensure_ascii=False)}
    async def unavailable_web(error):
        if error.failure.code != 'web_network' or error.failure.cancelled:
            raise error
        from app.agent.tools.resources.web import unavailable
        value = call.get('args', {}).get('url' if call['name'] == 'web_fetch' else 'query', '')
        content = await unavailable(context, value, error.failure.message,
                                    is_fetch=call['name'] == 'web_fetch', code=error.failure.code)
        return ToolMessage(content=content, tool_call_id=call['id'], name=call['name'])
    return await execute_node(context, identity=identity, kind='tool', label=label, operation=operation,
                              presentation=presentation,
                              result_presentation=lambda result: tool_presentation(call['name'], call.get('args'), result),
                              outcome=outcome, encode=lambda m: {'content': m.content, 'tool_call_id': m.tool_call_id, 'name': m.name, 'status': m.status, 'id': m.id},
                              decode=lambda data: ToolMessage(**data),
                              safe_replay=call['name'] in REPLAYABLE_TOOLS,
                              allow_work_refresh=refreshing_work,
                              restore=restore_receipt if call['name'] == 'execute_business_action' else restore_memory if call['name'] in ('save_memory', 'forget_memory') else None,
                              on_failure=unavailable_web if call['name'] in ('web_search', 'web_fetch') else None,
                              receipt_output=lambda result: ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call['id'], name=call['name']))
