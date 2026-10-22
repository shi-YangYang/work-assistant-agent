import json
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from app.agent.tools.catalog import allowed_tools, available_groups, catalog_schema, loaded_groups, remember_call_capability, visible_tools
from app.agent.prompts.main import capability_policy
from app.tasks.context import ToolBudgetExceeded
from app.tasks.lease import lease
from app.agent.runtime import decision_flow


def repairing_delivery(messages, job_id):
    latest = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
    return latest is not None and latest.id in (f'delivery-repair:{job_id}', f'delivery-references:{job_id}')


class ToolBoundary(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            groups = loaded_groups(context, job)
            decision = decision_flow.refresh(context, job)
            from app.tasks.budget import service as budget
            from app.tasks.budget.state import TaskBudgetStopped
            budget.ensure(job, context)
            from app.agent.runtime.tool_progress.service import research_stopped
            research_closed = research_stopped(context, job, request.messages)
            snapshot = budget.current(context)
            if snapshot and snapshot['phase'] in ('exhausted', 'ended'):
                raise TaskBudgetStopped(snapshot['reason'])
            finish_only = snapshot and snapshot['phase'] == 'finalizing'
            if context.refresh_work_versions:
                from app.security.versions import validate_cached_versions
                await validate_cached_versions(db, actor, context.read_versions,
                                               refresh_work_versions=context.refresh_work_versions)
            material_destination_gap = any(entry.get('recovery', {}).get('materialSelectionId')
                                           and entry.get('category') == 'missing_info'
                                           for entry in job.result.get('toolOutcomes', []))
        if context.refresh_work_versions and not finish_only:
            reads = [tool for tool in request.tools if (tool.name if hasattr(tool, 'name') else tool.get('name', tool.get('function', {}).get('name'))) == 'get_work_item']
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + '\n工作写入遇到版本冲突，旧正文不能继续用于保存或收尾。现在仅调用 get_work_item，work_id 从以下服务端确认的目标选择，body_start=0：' + json.dumps(sorted(context.refresh_work_versions), ensure_ascii=False) + '。读取最新内容后再按用户原请求修改，保留人工新增内容。')
            return await handler(request.override(tools=reads, system_message=system,
                                                  tool_choice={'type': 'function', 'function': {'name': 'get_work_item'}}))
        from app.agent.actions.interactions import waiting_text
        if material_destination_gap:
            from app.agent.actions.material_questions import ask_destination
            await ask_destination(context)
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
            from app.agent.runtime.budget import final_answer_call
            token = final_answer_call.set(True)
            try:
                return await handler(request.override(tools=[], system_message=system, tool_choice='none',
                    model_settings={**getattr(request, 'model_settings', {}), 'tool_choice': 'none'}))
            finally:
                final_answer_call.reset(token)
        if finish_only:
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + '\n直接交付已有结果与尚未完成的范围，不再调用工具，不编造结果。不向用户解释内部执行限制。')
            from app.agent.runtime.budget import final_answer_call
            token = final_answer_call.set(True)
            try:
                # The framework's empty-tools branch binds model_settings only;
                # request.tool_choice alone never reaches the HTTP payload.
                return await handler(request.override(tools=[], system_message=system, tool_choice='none',
                    model_settings={**getattr(request, 'model_settings', {}), 'tool_choice': 'none'}))
            finally:
                final_answer_call.reset(token)
        names = decision_flow.available(decision, visible_tools(context, groups))
        if research_closed:
            from app.agent.runtime.tool_progress.research import TOOLS, has_snapshot
            names -= TOOLS
            if has_snapshot(context.web_pages):
                names.add('web_fetch')
        offered = [tool for tool in visible if (tool.name if hasattr(tool, 'name') else tool.get('name', tool.get('function', {}).get('name'))) in names]
        policy_groups = groups if 'research' in groups or 'web_search' not in names else [*groups, 'research']
        policy = capability_policy(policy_groups, context.role)
        if research_closed:
            from app.agent.runtime.tool_progress.research import NOTICE
            policy += '\n' + NOTICE + ' web_fetch 仅能读取保留的页面快照。'
        policy += '\n' + decision_flow.policy(decision) + decision_flow.notice(decision)
        system = SystemMessage(content=(request.system_message.text if request.system_message else '') + ('\n' + policy if policy else ''))
        excluded = {group for group, tools in available_groups(context).items() if not decision_flow.available(decision, tools)}
        if research_closed:
            excluded.add('research')
        result = await handler(request.override(tools=decision_flow.schemas([catalog_schema(context, exclude=excluded), *offered], first=not decision['calls'], reviewing=bool(decision['requirements']), tracking=True), system_message=system, tool_choice='auto'))
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            for message in result.result:
                if isinstance(message, AIMessage):
                    decision_flow.receive(context, job, message)
        return result

    async def awrap_tool_call(self, request, handler):
        context = request.runtime.context
        from app.agent.runtime.tool_progress import begin, end
        from app.core.digests import digest
        batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
        call, flow = decision_flow.clean(request.tool_call)
        if call != request.tool_call:
            request = request.override(tool_call=call)
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            if call['name'] not in allowed_tools(context) | {'load_tools'}:
                raise RuntimeError('Tool is not allowed')
            stopped = decision_flow.begin(context, job, call, batch, flow)
            independent_call = decision_flow.current(context, job)['calls'].get(decision_flow.identity(batch, call), {}).get('independent', False)
        if stopped is not None:
            return stopped
        progress_call = {**call, 'progressId': digest({'message': getattr(batch, 'id', None), 'call': call['id']}),
                         'decisionId': decision_flow.identity(batch, call)}

        async def complete(result):
            return await end(context, progress_call, result)
        if batch:
            from app.agent.runtime.tool_progress.research import TOOLS
            peers = [digest({'message': batch.id, 'call': call['id']}) for call in batch.tool_calls if call['name'] in TOOLS]
            progress_call.update(progressBatch=digest({'message': batch.id, 'calls': peers}), progressPeers=peers)
        stopped = await begin(context, progress_call)
        if stopped is not None:
            return stopped

        async def reject(code, message, *, conflict=False, **extra):
            result = ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], status='error',
                content=json.dumps({'state': 'conflict' if conflict else 'not_executed', 'category': 'conflict' if conflict else 'invalid_arguments',
                                    'executed': False, 'code': code, 'message': message}, ensure_ascii=False), **extra)
            return await complete(result)

        if context.refresh_work_versions and not (request.tool_call['name'] == 'get_work_item' and
                                                 request.tool_call.get('args', {}).get('work_id') in context.refresh_work_versions and
                                                 request.tool_call.get('args', {}).get('body_start', 0) == 0):
            return await reject('work_refresh_required', '先用 get_work_item 从正文第一页读取冲突工作的最新版本，再继续保存或收尾。', conflict=True)
        if repairing_delivery(request.state.get('messages', []), context.job_id):
            return await reject('delivery_only', '本轮仅修复答复，此工具未执行。请直接交付完整正文，不调用工具。')
        if batch and len(batch.tool_calls) > 1 and any(call['name'] == 'finish_task' for call in batch.tool_calls):
            return await reject('mixed_finish', '收尾必须单独调用；本批工具均未执行。先执行所需工具，观察结果后再 finish_task。')
        if batch and any(call['name'] == 'set_task_context' for call in batch.tool_calls) and any(call['name'] in ('execute_business_action', 'propose_progress', 'propose_followup') for call in batch.tool_calls):
            return await reject('mixed_context_write', '任务上下文变更与业务写入不能同批；本批未执行，请先记录上下文，再进行写入。')
        if request.tool_call['name'] == 'finish_task':
            from app.agent.completion.delivery import completion_reference_error
            args = request.tool_call['args']
            error = await completion_reference_error(context, args.get('operation_ids'),
                verification_requested=args.get('verification_requested', False), verification_quote=args.get('verification_quote', ''))
            if error:
                return await reject('invalid_completion', error, additional_kwargs={'completion_reference_error': True})
            return await complete(await handler(request))
        if request.tool_call['name'] == 'load_tools':
            return await complete(await handler(request))
        if batch and request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_', 'web_')) and any(call['name'] == 'execute_business_action' for call in batch.tool_calls):
            return await reject('mixed_read_write', '本批次含写操作，本查询尚未执行。请等写操作返回后，在下一批调用查询更新后的结果。')
        if batch and not independent_call and any(call['name'] == 'request_user_input' for call in batch.tool_calls) and request.tool_call['name'] in ('execute_business_action', 'propose_progress', 'propose_followup'):
            return await reject('mixed_question_write', '本批次正在提问，等待用户回答后再执行写操作')
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            remember_call_capability(context, job, request.tool_call)
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_', 'web_')):
            from app.tasks.feedback.feedback import publish
            await publish(context, 'searching', force=True)
        from app.agent.runtime.tool_nodes import reject_tool_budget, tool_node
        if not context.node_retry:
            if context.tools >= 16:
                return await complete(await reject_tool_budget(context, request.tool_call))
            context.tools += 1
        try:
            if context.timing:
                with context.timing.span('tool', call=request.tool_call['id'], kind=request.tool_call['name']):
                    return await complete(await tool_node(context, request, lambda: handler(request)))
            return await complete(await tool_node(context, request, lambda: handler(request)))
        except ToolBudgetExceeded:
            return await complete(await reject_tool_budget(context, request.tool_call))
