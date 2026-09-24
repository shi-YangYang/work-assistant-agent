"""Controlled tool labels and structured outcomes for the assistant UI."""
import json
from langchain_core.messages import ToolMessage
from app.tasks.node_execution import execute_node

LABELS = {
    'find_work_items': '查找工作', 'get_work_item': '读取工作',
    'get_message_context': '读取消息', 'get_business_actions': '读取操作结果',
    'query_reports': '查找报告', 'query_report_obligations': '查找汇报待办',
    'find_documents': '查找文件', 'read_document': '读取文件', 'read_file': '读取材料',
    'find_team_members': '查找成员', 'query_team_business': '查询团队工作',
    'read_team_source': '读取团队来源', 'propose_progress': '整理进展建议',
    'propose_followup': '整理督办建议', 'draft_report': '整理报告',
}
ACTIONS = {'create_work': '创建工作', 'update_work': '更新工作', 'delete_work': '准备删除确认',
           'generate_report': '报告生成入队', 'edit_report': '修改报告',
           'submit_report': '准备提交确认', 'delete_report': '准备删除确认'}


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
    label = ACTIONS.get(call.get('args', {}).get('action'), '执行业务操作') if call['name'] == 'execute_business_action' else LABELS.get(call['name'], '处理材料')
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
    return await execute_node(context, identity=identity, kind='tool', label=label, operation=operation,
                              outcome=outcome, encode=lambda m: {'content': m.content, 'tool_call_id': m.tool_call_id, 'name': m.name, 'status': m.status, 'id': m.id},
                              decode=lambda data: ToolMessage(**data),
                              safe_replay=call['name'] in LABELS or call['name'] == 'execute_business_action',
                              restore=restore_receipt if call['name'] == 'execute_business_action' else None,
                              receipt_output=lambda result: ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call['id'], name=call['name']))
