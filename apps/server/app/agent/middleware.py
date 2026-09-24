import json
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from app.agent.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES
from app.agent.tools.common import claims_followup, explicit_followup
from app.modules.messages.models import Message
from app.modules.work.models import ProgressDraft
from app.security.access import inherit as business_inherit, require as business_require
from app.security.ownership import owned
from app.tasks.context import BudgetExceeded
from app.tasks.lease import lease
from sqlalchemy import select


class ToolBoundary(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions() as db:
            await lease(db, context)
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
        response = await handler(request.override(tools=visible))
        return await self.ensure_followup_result(request.override(tools=visible), response, handler)

    async def ensure_followup_result(self, request, response, handler):
        """A textual promise is not a persisted draft. Repair at most once.

        This uses the same model reservation/time/tool budgets. It never picks
        sources or creates a draft itself, and a clarification is a valid end.
        The correction marker is durable so restoring a checkpoint cannot loop.
        """
        context = request.runtime.context
        answer = next((m for m in reversed(response.result) if isinstance(m, AIMessage)), None)
        if context.role != 'admin' or not answer or answer.tool_calls or not claims_followup(answer.text):
            return response
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            if job.kind != 'message':
                return response
            from app.modules.operations.models import BusinessAction
            if await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == job.target_id).limit(1)):
                return response
            message = await owned(db, Message, job.target_id, actor)
            if not explicit_followup(message.text + '\n' + message.transcript):
                return response
            drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == message.id, ProgressDraft.owner_id == actor.id, ProgressDraft.status == 'pending'))).all()
            if drafts:
                for draft in drafts:
                    business_inherit(actor, draft, job)
                    await business_require(db, actor, draft.access)
                return response
            repair = not job.result.get('followupCorrectionAttempted') and context.own_work_searched and any(q['total'] for q in job.result.get('businessQueries', []))
            if repair:
                job.result = {**job.result, 'followupCorrectionAttempted': True}
        if repair:
            instruction = '\n服务端核对：本次尚无已保存的待确认建议或业务操作结果。若用户明确要求创建或更新本人督办，目标、内容和来源已明确，调用 execute_business_action 真正执行；仅当用户要求先给建议时用 propose_followup 保存建议。只使用此前真实返回的来源 token 和本人工作 ID。若仍有同名或指代歧义，请提问澄清，不要创建。不得仅用文字声称工作或建议已经生成。'
            system = SystemMessage(content=(request.system_message.text if request.system_message else '') + instruction)
            corrected = await handler(request.override(system_message=system))
            return await self.ensure_followup_result(request, corrected, handler)
        return ModelResponse(result=[AIMessage(id=answer.id, content='尚未生成可确认的督办建议，未创建或修改工作。请补充需要跟进的员工和事项，或稍后重新提出请求。')])

    async def awrap_tool_call(self, request, handler):
        context = request.runtime.context
        async with context.sessions() as db:
            await lease(db, context)
        allowed = ALLOWED_TOOLS | (TEAM_TOOL_NAMES if context.role == 'admin' else frozenset())
        if request.tool_call['name'] not in allowed:
            raise RuntimeError('Tool is not allowed')
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_')):
            from app.tasks.feedback import publish
            await publish(context, 'searching', force=True)
        context.tools += 1
        if context.tools > 16:
            raise BudgetExceeded('本次处理步骤已达到限制')
        if request.tool_call['name'].startswith(('find_', 'get_', 'query_', 'read_')):
            batch = next((m for m in reversed(request.state.get('messages', [])) if isinstance(m, AIMessage)), None)
            if batch and any(call['name'] == 'execute_business_action' for call in batch.tool_calls):
                return ToolMessage(tool_call_id=request.tool_call['id'], name=request.tool_call['name'], content=json.dumps({'error': '本批次含写操作，本查询尚未执行。请等写操作返回后，在下一批调用查询更新后的结果。'}, ensure_ascii=False))
        return await handler(request)
