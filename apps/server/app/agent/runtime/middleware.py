import json
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from app.agent.tools.catalog import allowed_tools, catalog_schema, loaded_groups, remember_legacy_call, visible_tools
from app.agent.prompts.main import capability_policy
from app.tasks.context import ToolBudgetExceeded
from app.tasks.lease import lease


def repairing_delivery(messages, job_id):
    latest = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
    return latest is not None and latest.id in (f'delivery-repair:{job_id}', f'delivery-references:{job_id}')


class ToolBoundary(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions() as db:
            job, actor = await lease(db, context)
            groups = loaded_groups(context, job)
            from app.tasks.nodes.node_state import execution
            state = execution(job) if context.node_retry else {}
            tool_count = sum(row['kind'] == 'tool' and row['scope'] == context.node_scope for row in state.get('nodes', [])) if context.node_retry else context.tools
            finish_only = tool_count >= 14 or state.get('actualCalls', context.calls) >= (29 if context.node_retry else 6)
            if context.refresh_work_versions:
                from app.security.versions import validate_cached_versions
                await validate_cached_versions(db, actor, context.read_versions,
                                               refresh_work_versions=context.refresh_work_versions)
        if context.refresh_work_versions:
            reads = [tool for tool in request.tools if (tool.name if hasattr(tool, 'name') else tool.get('name', tool.get('function', {}).get('name'))) == 'get_work_item']
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + '\n工作写入遇到版本冲突，旧正文不能继续用于保存或收尾。现在仅调用 get_work_item，work_id 从以下服务端确认的目标选择，body_start=0：' + json.dumps(sorted(context.refresh_work_versions), ensure_ascii=False) + '。读取最新内容后再按用户原请求修改，保留人工新增内容。')
            return await handler(request.override(tools=reads, system_message=system,
                                                  tool_choice={'type': 'function', 'function': {'name': 'get_work_item'}}))
        from app.agent.actions.interactions import waiting_text
        waiting = await waiting_text(context, include_actions=any(isinstance(message, ToolMessage) and message.name == 'execute_business_action' for message in request.messages))
        if waiting:
            return ModelResponse(result=[AIMessage(id=f'interaction-wait:{context.job_id}', content=waiting)])
        from app.agent.completion.completion import receipt_completion
        if await receipt_completion(context, request.messages):
            # Independent intent approval plus the committed receipt suffice
            # for operation-only requests; no success prose needs generating.
            return ModelResponse(result=[AIMessage(id=f'receipt-completion:{context.job_id}', content='')])
        allowed = allowed_tools(context)
        names = {t.name if hasattr(t, 'name') else t.get('name', t.get('function', {}).get('name')) for t in request.tools}
        # All implementations remain registered for old checkpoints; every actual
        # invocation still crosses the independent authorization boundary below.
        visible = [t for t in request.tools if (t.name if hasattr(t, 'name') else t.get('name', t.get('function', {}).get('name'))) in allowed]
        if not allowed.issubset(names):
            raise RuntimeError('Business tool set is incomplete')
        protocol_repair = repairing_delivery(request.messages, context.job_id)
        if protocol_repair:
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + '\n本轮仅修复答复格式或引用。直接交付完整正文，保留真实未完成项；不填写内部表单，不再调用工具或重做业务操作。')
            return await handler(request.override(tools=[], system_message=system, tool_choice='none'))
        if finish_only:
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + '\n本轮探索额度已接近上限。直接交付已有结果与尚未完成的范围，不再调用工具，不编造结果。')
            return await handler(request.override(tools=[], system_message=system, tool_choice='none'))
        names = visible_tools(context, groups)
        offered = [tool for tool in visible if (tool.name if hasattr(tool, 'name') else tool.get('name', tool.get('function', {}).get('name'))) in names]
        policy = capability_policy(groups, context.role)
        system = SystemMessage(content=(request.system_message.text if request.system_message else '') + ('\n' + policy if policy else ''))
        return await handler(request.override(tools=[catalog_schema(context), *offered], system_message=system, tool_choice='auto'))

    async def awrap_tool_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions() as db:
            await lease(db, context)
        allowed = allowed_tools(context)
        if request.tool_call['name'] not in allowed | {'load_tools'}:
            raise RuntimeError('Tool is not allowed')
        if context.refresh_work_versions and not (request.tool_call['name'] == 'get_work_item' and
                                                 request.tool_call.get('args', {}).get('work_id') in context.refresh_work_versions and
                                                 request.tool_call.get('args', {}).get('body_start', 0) == 0):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], status='error',
                               content=json.dumps({'state': 'conflict', 'message': '先用 get_work_item 从正文第一页读取冲突工作的最新版本，再继续保存或收尾。',
                                                   'workIds': sorted(context.refresh_work_versions)}, ensure_ascii=False))
        if repairing_delivery(request.state.get('messages', []), context.job_id):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content='本轮仅修复答复，此工具未执行。请直接交付完整正文，不调用工具。', status='error')
        batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
        if batch and len(batch.tool_calls) > 1 and any(call['name'] == 'finish_task' for call in batch.tool_calls):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content='收尾必须单独调用；本批工具均未执行。先执行所需工具，观察结果后再 finish_task。', status='error')
        if batch and any(call['name'] == 'set_task_context' for call in batch.tool_calls) and any(call['name'] in ('execute_business_action', 'propose_progress', 'propose_followup') for call in batch.tool_calls):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], status='error', content='任务上下文变更与业务写入不能同批；本批未执行，请先记录上下文，再进行写入。')
        if request.tool_call['name'] == 'finish_task':
            # A completion is metadata, not a business tool/node or a new model call.
            from app.agent.completion.delivery import completion_reference_error
            args = request.tool_call['args']
            error = await completion_reference_error(context, args.get('operation_ids'),
                                                     verification_requested=args.get('verification_requested', False),
                                                     verification_quote=args.get('verification_quote', ''))
            if error:
                return ToolMessage(tool_call_id=request.tool_call['id'], name='finish_task', content=error, status='error',
                                   additional_kwargs={'completion_reference_error': True})
            return await handler(request)
        if request.tool_call['name'] == 'load_tools':
            # Discovery is idempotent task metadata, not a business/read node.
            # Subsequent model requests retain their original call/time budgets.
            return await handler(request)
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            remember_legacy_call(context, job, request.tool_call)
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_', 'web_')):
            from app.tasks.feedback.feedback import publish
            await publish(context, 'searching', force=True)
        from app.agent.runtime.tool_nodes import reject_tool_budget, tool_node
        if not context.node_retry:
            if context.tools >= 16:
                return await reject_tool_budget(context, request.tool_call)
            context.tools += 1
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_', 'web_')):
            batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
            if batch and any(call['name'] == 'execute_business_action' for call in batch.tool_calls):
                return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content=json.dumps({'error': '本批次含写操作，本查询尚未执行。请等写操作返回后，在下一批调用查询更新后的结果。'}, ensure_ascii=False))
        batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
        if batch and any(call['name'] == 'request_user_input' for call in batch.tool_calls) and request.tool_call['name'] in ('execute_business_action', 'propose_progress', 'propose_followup'):
            return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content=json.dumps({'state': 'waiting', 'message': '本批次正在提问，等待用户回答后再执行写操作'}, ensure_ascii=False))
        try:
            if context.timing:
                with context.timing.span('tool', call=request.tool_call['id'], kind=request.tool_call['name']):
                    return await tool_node(context, request, lambda: handler(request))
            return await tool_node(context, request, lambda: handler(request))
        except ToolBudgetExceeded:
            return await reject_tool_budget(context, request.tool_call)
