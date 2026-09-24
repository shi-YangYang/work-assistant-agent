import asyncio
import json
import time
from fastapi import HTTPException
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from app.db.base import now
from app.modules.model_services.models import ModelUsage
from app.tasks.context import BudgetExceeded, InputChanged, LostLease, RunContext
from app.tasks.lease import lease
from pydantic import PrivateAttr


def approximate_tokens(messages):
    total = 0
    for message in messages:
        content = message.content
        if isinstance(content, str):
            total += len(content)  # Conservative for Chinese; avoids tokenizer model downloads.
        else:
            for block in content:
                total += 2048 if isinstance(block, dict) and block.get('type') == 'image_url' else len(str(block))
    return total


async def reserve_call(context, kind, estimate=0):
    if context.calls >= 8 or context.tools > 16 or time.monotonic() - context.started > 180 or context.input_tokens + estimate > 64000 or context.output_tokens >= 8000:
        raise BudgetExceeded('本次处理已达到限制，请缩短内容后重试或补充说明')
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        from app.modules.model_services.usage import usage_fields
        usage = ModelUsage(company_id=context.company_id, owner_id=context.owner_id, job_id=context.job_id, kind=kind, input_tokens=estimate, **usage_fields((context.model_binding or {}).get(kind), attempt=job.attempt, fence=job.fence))
        db.add(usage)
        job.request_started, job.phase, job.updated_at = True, kind, now()
        if job.kind == 'report':
            from app.tasks.feedback_state import update_feedback
            update_feedback(job, 'generating', '')
        await db.flush()
        usage_id = usage.id
    context.calls += 1
    context.input_tokens += estimate
    return usage_id


class BoundedChatModel(ChatOpenAI):
    _run_context: RunContext = PrivateAttr()
    _verification: bool = PrivateAttr(default=False)
    _verification_reasoning: bool = PrivateAttr(default=False)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        context = self._run_context
        estimate = approximate_tokens(messages)
        if estimate > 24000:
            raise BudgetExceeded('本次上下文较长，请分段上报')
        from app.modules.model_services.bindings import resolve_bound
        from app.integrations.models.chat import chat
        from app.integrations.models.transport import safe_error
        from app.modules.model_services.usage import RequestRecord
        from app.tasks.feedback import publish
        usage_id = await reserve_call(context, context.model_purpose, estimate)
        record = RequestRecord(context.sessions, usage_id)
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        is_reply = bool(payload.get('tools')) and context.model_purpose == 'assistant'
        if is_reply:
            await publish(context, 'generating', call_id=usage_id, force=True)
        try:
            async with context.sessions() as db:
                await lease(db, context)
                config, key = await resolve_bound(db, context.settings, context.company_id, context.model_binding or {}, context.model_purpose)
            output_limit = min(4000, self.max_tokens or 4000, 8000 - context.output_tokens)
            if self._verification:
                from app.modules.model_services.parameters import reply_review_config
                config = reply_review_config(config, reasoning=self._verification_reasoning)
            elif is_reply:
                from app.modules.model_services.parameters import business_model_config
                config = business_model_config(config, (context.model_binding or {}).get('assistant') or {})
            # Publish phase transitions, not an identical empty snapshot for each
            # token. Prose still passes review before becoming user-visible.
            response = await record.run(lambda event: asyncio.wait_for(chat(context.settings, config, key, payload['messages'], tools=payload.get('tools'), tool_choice=payload.get('tool_choice'), max_tokens=output_limit, on_event=event), 60))
            # Framework conversion/tool validation remains after a fully received
            # provider response. A later business failure is not a request failure.
            result = self._create_chat_result(response)
        except Exception as error:
            await record.finish(error)
            if isinstance(error, (LostLease, InputChanged, HTTPException)):
                raise
            raise safe_error(error) from None
        output = sum((g.message.usage_metadata or {}).get('output_tokens', 0) or len(str(g.message.content)) + len(json.dumps(g.message.tool_calls, ensure_ascii=False)) for g in result.generations)
        context.output_tokens += output
        async with context.sessions.begin() as db:
            await lease(db, context)
            usage = await db.get(ModelUsage, usage_id)
            usage.output_tokens = output
        if context.output_tokens > 8000:
            raise BudgetExceeded('模型响应超过本次输出限制，已停止后续处理')
        return result

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        # Even framework streaming goes through the same reservation and complete
        # response validation; no tool is exposed from a partial wire stream.
        result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for generation in result.generations:
            message = generation.message
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content, tool_calls=message.tool_calls, usage_metadata=message.usage_metadata), generation_info=generation.generation_info)
