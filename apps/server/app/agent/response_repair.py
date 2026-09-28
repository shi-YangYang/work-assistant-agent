"""One conditional, text-only correction after the independent reply review."""
import json
from langchain_core.messages import HumanMessage, SystemMessage
from app.agent.model import BoundedChatModel
from app.agent.persona import persona_prompt
from app.agent.context_usage import estimate_request, ensure_input
from app.core.digests import digest
from app.modules.messages.input_text import request_text
from app.modules.messages.models import Message
from app.modules.operations.receipts import message_actions
from app.security.ownership import owned
from app.tasks.lease import lease
from app.tasks.node_execution import execute_node


async def repair_response(context, answer, reason, *, model=None):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        payload = {'request': request_text(message, job), 'candidate': answer, 'correction': reason,
            'currentActions': await message_actions(db, actor, message), 'evidence': context.reply_evidence}
    messages = [SystemMessage(content='只修正当前用户要求的必要答复正文。没有工具执行权限，不创建、修改或承诺额外操作。以逐项 currentActions.details/changedFields 和 evidence 为准；操作保存成功不等于工作已完成。补足 correction 指出的必要内容，保留正确的其它答复；没有依据不编造，也不把工具的系统问题推给用户重复授权。确缺用户输入时只补最小必要问题，已有查询中的对象候选与区分字段原样准确呈现；没有查到候选就请用户提供定位信息，不能自行造选项或替用户回答。\n' + persona_prompt(context.persona_id)), HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str))]
    ensure_input(context, estimate_request(messages))
    if model is None:
        choice = (context.model_binding or {}).get('assistant') or {}
        model = BoundedChatModel(model=choice.get('model', 'unconfigured'), api_key='server-managed', max_retries=0, timeout=60, max_tokens=4000, streaming=False, use_responses_api=False, stream_usage=False)
        model._run_context = context
    async def generate():
        from app.integrations.models.transport import ProviderError
        response = await model.ainvoke(messages)
        if response.tool_calls or not response.text.strip():
            raise ProviderError('invalid_response', '正文修正未返回有效文本')
        return response.text
    return await execute_node(context, identity='response-repair:' + digest(payload), kind='model', label='完善答复中', operation=generate)
