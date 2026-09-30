"""Controlled tool labels and structured outcomes for the assistant UI."""
import json
from langchain_core.messages import ToolMessage
from app.tasks.nodes.node_execution import execute_node
from app.agent.runtime.progress.tools import tool_presentation


# Replay safety is an execution policy, independent of display-label registration.
REPLAYABLE_TOOLS = frozenset({
    'inspect_table', 'export_table', 'create_chart', 'create_document', 'create_slides',
    'run_python', 'request_user_input', 'find_work_items', 'get_work_item',
    'get_message_context', 'get_business_actions', 'query_reports', 'query_report_obligations',
    'find_documents', 'read_document', 'read_file', 'find_team_members', 'query_team_business',
    'read_team_source', 'propose_progress', 'propose_followup', 'save_deliverable',
    'read_deliverable', 'read_execution', 'web_search', 'web_fetch', 'execute_business_action',
})


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
        if value.get('category') == 'permission_denied':
            return 'failed', '当前权限无法执行'
        if state == 'not_requested':
            return 'cancelled', '本次未要求该操作'
        if 'error' in value or state in ('failed', 'conflict', 'unavailable', 'cancelled'):
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
    async def restore_receipt(db, actor, value):
        from app.modules.operations.models import BusinessAction
        from app.modules.operations.receipts import action_dto
        from app.security.ownership import owned
        result = json.loads(value['content'])
        if isinstance(result, dict) and result.get('id'):
            row = await owned(db, BusinessAction, result['id'], actor)
            return {**value, 'content': json.dumps(await action_dto(db, actor, row), ensure_ascii=False)}
        return value
    async def unavailable_web(error):
        if error.failure.code != 'web_network' or error.failure.cancelled:
            raise error
        from app.agent.tools.web import unavailable
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
                              restore=restore_receipt if call['name'] == 'execute_business_action' else None,
                              on_failure=unavailable_web if call['name'] in ('web_search', 'web_fetch') else None,
                              receipt_output=lambda result: ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call['id'], name=call['name']))
