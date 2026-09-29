import json
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from app.agent.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES
from app.tasks.context import BudgetExceeded
from app.tasks.lease import lease


class ToolBoundary(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions() as db:
            job, _ = await lease(db, context)
            from app.tasks.node_state import execution
            state = execution(job) if context.node_retry else {}
            tool_count = sum(row['kind'] == 'tool' and row['scope'] == context.node_scope for row in state.get('nodes', [])) if context.node_retry else context.tools
            finish_only = tool_count >= 14 or state.get('actualCalls', context.calls) >= (29 if context.node_retry else 6)
        from app.agent.interactions import waiting_text
        waiting = await waiting_text(context, include_actions=any(isinstance(message, ToolMessage) and message.name == 'execute_business_action' for message in request.messages))
        if waiting:
            return ModelResponse(result=[AIMessage(id=f'interaction-wait:{context.job_id}', content=waiting)])
        from app.agent.completion import receipt_completion
        if await receipt_completion(context, request.messages):
            # Independent intent approval plus the committed receipt suffice
            # for operation-only requests; no success prose needs generating.
            return ModelResponse(result=[AIMessage(id=f'receipt-completion:{context.job_id}', content='')])
        allowed = ALLOWED_TOOLS | (TEAM_TOOL_NAMES if context.role == 'admin' else frozenset())
        names = {t.name if hasattr(t, 'name') else t.get('name', t.get('function', {}).get('name')) for t in request.tools}
        # Profiles tune model visibility; this middleware is the security boundary.
        visible = [t for t in request.tools if (t.name if hasattr(t, 'name') else t.get('name', t.get('function', {}).get('name'))) in allowed]
        if not allowed.issubset(names):
            raise RuntimeError('Business tool set is incomplete')
        if finish_only:
            terminal = [tool for tool in visible if (tool.name if hasattr(tool, 'name') else tool.get('name', tool.get('function', {}).get('name'))) == 'finish_task']
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + '\n本轮探索额度已接近上限。立即使用 finish_task 交付已有结果、实际来源及未完成范围，不再读取或执行工具。不能编造缺失内容，不能把尚未完成的事项标为完成。')
            return await handler(request.override(tools=terminal, system_message=system, tool_choice={'type': 'function', 'function': {'name': 'finish_task'}}))
        return await handler(request.override(tools=visible))

    async def awrap_tool_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions() as db:
            await lease(db, context)
        allowed = ALLOWED_TOOLS | (TEAM_TOOL_NAMES if context.role == 'admin' else frozenset())
        if request.tool_call['name'] not in allowed:
            raise RuntimeError('Tool is not allowed')
        batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
        if batch and len(batch.tool_calls) > 1 and any(call['name'] == 'finish_task' for call in batch.tool_calls):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content='收尾必须单独调用；本批工具均未执行。先执行所需工具，观察结果后再 finish_task。', status='error')
        if request.tool_call['name'] == 'finish_task':
            # A completion is metadata, not a business tool/node or a new model call.
            return await handler(request)
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_', 'web_')):
            from app.tasks.feedback import publish
            await publish(context, 'searching', force=True)
        if not context.node_retry:
            context.tools += 1
        if context.tools > 16:
            raise BudgetExceeded('本次处理步骤已达到限制')
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_', 'web_')):
            batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
            if batch and any(call['name'] == 'execute_business_action' for call in batch.tool_calls):
                return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content=json.dumps({'error': '本批次含写操作，本查询尚未执行。请等写操作返回后，在下一批调用查询更新后的结果。'}, ensure_ascii=False))
        batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
        if batch and any(call['name'] == 'request_user_input' for call in batch.tool_calls) and request.tool_call['name'] in ('execute_business_action', 'propose_progress', 'propose_followup'):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content=json.dumps({'state': 'waiting', 'message': '本批次正在提问，等待用户回答后再执行写操作'}, ensure_ascii=False))
        from app.agent.tool_nodes import tool_node
        try:
            return await tool_node(context, request, lambda: handler(request))
        except BudgetExceeded:
            async with context.sessions() as db:
                job, _ = await lease(db, context)
                from app.tasks.node_state import execution
                count = sum(row['kind'] == 'tool' and row['scope'] == context.node_scope for row in execution(job).get('nodes', []))
            if count < 16:
                raise
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content=json.dumps({'state': 'unavailable', 'message': '本轮工具额度已用完；此工具未执行。请立即用已有结果 finish_task，说明未完成范围。'}, ensure_ascii=False))
