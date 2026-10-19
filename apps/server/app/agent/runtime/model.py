import asyncio
import json
import time
from contextvars import ContextVar
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from app.db.base import now
from app.modules.model_services.models import ModelUsage
from app.tasks.context import BudgetExceeded, RunContext
from app.tasks.lease import lease
from pydantic import PrivateAttr


# A shared model may serve internal work and user replies concurrently.
from app.agent.runtime.budget import internal_call_kind


def approximate_tokens(messages):
    from app.agent.context.context_usage import estimate_request
    return estimate_request(messages)


def response_timeout(context, streaming):
    if not context.node_retry:
        return 60
    remaining = max(.01, context.node_deadline - time.time())
    return remaining if streaming else min(60, remaining)


async def request_with_deadline(request, *, timeout, idle_timeout=None):
    """Only useful generation progress renews idle time, never the total deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    async with asyncio.timeout_at(min(deadline, loop.time() + idle_timeout) if idle_timeout is not None else deadline) as guard:
        def progress():
            guard.reschedule(min(deadline, loop.time() + idle_timeout))
        return await request(progress if idle_timeout is not None else None)


async def reserve_call(context, kind, estimate=0, *, final_answer=False):
    from app.agent.context.context_usage import input_budget, MAX_CONTEXT_BYTES
    from app.tasks.budget import service as budget
    from app.tasks.budget.state import policy
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        state = budget.ensure(job, context)
        maximum = policy(state).models if state else 8
        cumulative = (input_budget(context, 0) or MAX_CONTEXT_BYTES) * maximum
        consumed_input = job.result.get('nodeExecution', {}).get('inputTokens', 0) if context.node_retry else context.input_tokens
        if consumed_input + estimate > cumulative:
            raise BudgetExceeded('累计输入超出可用处理范围，请减少材料后重试')
        if state:
            budget.consume(job, context, 'model', final_answer=final_answer)
        elif context.calls >= 8 or context.tools > 16 or time.monotonic() - context.started > 180 or context.output_tokens >= 8000:
            raise BudgetExceeded('本次处理已达到限制，请缩短内容后重试或补充说明')
        from app.modules.model_services.usage.usage import usage_fields
        usage = ModelUsage(company_id=context.company_id, owner_id=context.owner_id, job_id=context.job_id, kind=kind, input_tokens=estimate, **usage_fields((context.model_binding or {}).get(kind), attempt=job.attempt, fence=job.fence))
        if context.node_retry:
            from app.tasks.nodes.node_state import execution
            nodes = execution(job)
            nodes['actualCalls'] = context.calls
            nodes['inputTokens'] = nodes.get('inputTokens', 0) + estimate
            job.result = {**job.result, 'nodeExecution': nodes}
        db.add(usage)
        job.request_started, job.phase, job.updated_at = True, kind, now()
        if job.kind == 'report':
            from app.tasks.feedback.feedback_state import update_feedback
            update_feedback(job, 'generating', '')
        await db.flush()
        usage_id = usage.id
    if not state:
        context.calls += 1
    context.input_tokens += estimate
    return usage_id


class BoundedChatModel(ChatOpenAI):
    _run_context: RunContext = PrivateAttr()
    _verification: bool = PrivateAttr(default=False)
    _verification_reasoning: bool = PrivateAttr(default=False)
    _response_validator: object = PrivateAttr(default=None)
    _completion_validator: object = PrivateAttr(default=None)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        from app.tasks.nodes.node_execution import active_node, execute_node
        from app.core.digests import digest
        context = self._run_context
        async def operation():
            return await self._single(messages, stop=stop, run_manager=run_manager, **kwargs)
        parent = active_node.get()
        if not context.node_retry or parent and parent[1] in ('authorization', 'review', 'compaction'):
            return await operation()
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        # Message ids are graph/checkpoint identities, not provider call counters.
        identity = digest({'request': payload, 'binding': context.model_binding, 'messages': [getattr(m, 'id', None) for m in messages]})
        from app.agent.runtime.progress import model_phase
        from app.agent.runtime.budget import final_answer_call
        label = '整理答复' if final_answer_call.get() else model_phase(messages, context.job_id, nested=bool(parent))
        return await execute_node(context, identity=identity, kind='model', label=label, operation=operation,
                                  presentation={'type': 'activity'},
                                  encode=encode_result, decode=decode_result, allow_work_refresh=True)

    async def _single(self, messages, stop=None, run_manager=None, **kwargs):
        context = self._run_context
        from app.agent.context.context_usage import estimate_request, ensure_input, output_reserve
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        from app.agent.runtime.budget import final_answer_call, instruction
        internal_kind = internal_call_kind.get()
        note = instruction(context) if not internal_kind and self._completion_validator else None
        budget_note_index = len(payload['messages'])
        if note:
            payload['messages'] = [*payload['messages'], {'role': 'system', 'content': note}]
        from app.agent.context.document_input import assemble_pages, project_document_messages, record_page_delivery, record_text_delivery
        text_messages = list(payload['messages'])
        document_pages = {}
        output_limit = output_reserve(context, self.max_tokens)
        if not internal_kind and not self._verification:
            payload['messages'], document_pages = await assemble_pages(context, payload['messages'], tools=payload.get('tools', ()), output_reserve=output_limit)
        payload['messages'], document_text = project_document_messages(context, payload['messages'])
        text_messages = payload['messages'][:len(text_messages)]
        estimate = estimate_request(payload['messages'], payload.get('tools', ()), document_images=False)
        ensure_input(context, estimate, output_limit)
        from app.modules.model_services.bindings import resolve_bound
        from app.integrations.models.chat import chat
        from app.integrations.models.transport import safe_error
        from app.modules.model_services.usage.usage import RequestRecord
        from app.tasks.feedback.feedback import publish
        async with context.sessions() as db:
            await lease(db, context)
            config, key = await resolve_bound(db, context.settings, context.company_id, context.model_binding or {}, context.model_purpose)
        usage_id = await reserve_call(context, context.model_purpose, estimate,
                                      final_answer=final_answer_call.get() and not internal_kind and bool(self._completion_validator))
        record = RequestRecord(context.sessions, usage_id)
        async def usage_event(event, value=None):
            await record.event(event, value)
        async def compatibility_retry(error):
            nonlocal record, usage_id
            await record.finish(error)
            usage_id = await reserve_call(context, context.model_purpose, estimate,
                                          final_answer=final_answer_call.get() and not internal_kind and bool(self._completion_validator))
            record = RequestRecord(context.sessions, usage_id)
            if note:
                payload['messages'][budget_note_index] = {'role': 'system', 'content': instruction(context)}
        from app.tasks.nodes.node_execution import active_node
        parent = active_node.get()
        from langchain_core.messages import HumanMessage
        marker = next((str(m.id or '') for m in reversed(messages) if isinstance(m, HumanMessage)), '')
        kind = ('protocol' if marker.startswith(('delivery-repair:', 'delivery-references:')) else
                'completion_repair' if marker.startswith('completion-repair:') else
                parent[1] if parent and parent[1] in ('authorization', 'compaction', 'review') else
                'main' if payload.get('tools') else 'response_repair')
        from app.tasks.timing import call_kind
        internal_kind = internal_call_kind.get()
        kind = internal_kind or call_kind.get() or kind
        def timing(event, **fields):
            if context.timing:
                context.timing.mark(event, call=usage_id, kind=kind, **fields)
        if note:
            payload['messages'][budget_note_index] = {'role': 'system', 'content': instruction(context)}
        is_reply = not internal_kind and bool(payload.get('tools') or self._completion_validator) and context.model_purpose == 'assistant'
        publisher = candidate = None
        if is_reply and not self._verification:
            from app.tasks.feedback.reply_stream import ReplyPublisher
            publisher = ReplyPublisher(context, usage_id)
            await publisher.start()
            from app.agent.runtime.reply_stream import ReplyCandidate, allows_reply_stream
            if config.get('streaming', False) and not context.access.get('team') and allows_reply_stream(messages, context.job_id, payload):
                candidate = ReplyCandidate(publisher)
        if is_reply:
            await publish(context, 'generating', call_id=usage_id, force=True)
        activity_phase = None
        async def activity(phase):
            nonlocal activity_phase
            if activity_phase != phase:
                from app.agent.runtime.progress.phases import model_activity
                await model_activity(context, phase)
                activity_phase = phase
        async def receive(delta):
            if candidate:
                await candidate.feed(delta)
            if candidate and candidate.text or not candidate and delta.text.strip() and not delta.tools:
                await activity('answering')
            elif delta.tools:
                await activity('tool_call')
            elif delta.reasoning and activity_phase in (None, 'waiting'):
                await activity('thinking')
        try:
            if self._verification:
                from app.modules.model_services.parameters import reply_review_config
                config = reply_review_config(config, reasoning=self._verification_reasoning)
            elif context.model_purpose == 'report':
                from app.modules.model_services.parameters import report_model_config
                config = report_model_config(config, (context.model_binding or {}).get('report') or {})
            elif is_reply:
                from app.modules.model_services.parameters import business_model_config
                config = business_model_config(config, (context.model_binding or {}).get('assistant') or {})
            # The optional callback publishes prose only; framework tools remain buffered.
            streaming = config.get('streaming', False)
            timeout = response_timeout(context, streaming)
            async def request(progress):
                if is_reply and not self._verification:
                    await activity('waiting')
                return await chat(context.settings, config, key, payload['messages'], tools=payload.get('tools'), tool_choice=payload.get('tool_choice'), max_tokens=None if context.model_purpose == 'assistant' else output_limit, text_tools=('finish_task',) if context.model_purpose == 'assistant' else (), on_event=usage_event, on_retry=compatibility_retry, on_timing=timing, on_delta=receive if is_reply and not self._verification else None, on_progress=progress, stream_timeout=timeout if streaming and context.node_retry else None)
            try:
                response = await request_with_deadline(request, timeout=timeout, idle_timeout=60 if streaming else None)
            except Exception as error:
                from app.integrations.models.transport import ProviderError
                if not document_pages or not isinstance(error, ProviderError) or error.code != 'protocol' or error.status not in (400, 415, 422) or not error.image_input_unsupported:
                    raise
                # One bounded, explicit degradation on rejected document pixels;
                # never retry quota/auth/network errors or change the model.
                async with context.sessions.begin() as db:
                    live, _ = await lease(db, context)
                    live.result = {**live.result, 'documentVisionDisabled': True}
                await compatibility_retry(error)
                payload['messages'] = [*text_messages, {'role': 'user', 'content': '本次文档页面图片未能提供，保留了可读文字。仅据已读内容作答，并说明图片部分没读到；不要猜测。'}]
                document_pages = {}
                response = await request_with_deadline(request, timeout=response_timeout(context, streaming), idle_timeout=60 if streaming else None)
            await record_page_delivery(context, document_pages)
            if not internal_kind and not self._verification:
                await record_text_delivery(context, text_messages, supplied=document_text)
            # Framework conversion/tool validation remains after a fully received
            # provider response. A later business failure is not a request failure.
            required_completion = payload.get('tool_choice') == {'type': 'function', 'function': {'name': 'finish_task'}}
            result = self._checked_chat_result(response, required_completion=required_completion,
                                               internal_kind=internal_kind, timing=timing)
            if self._response_validator:
                self._response_validator(result.generations[0].message)
            if context.node_retry:
                from app.tasks.nodes.node_execution import active_node
                for index, generation in enumerate(result.generations):
                    generation.message.id = f'node:{active_node.get()[0]}:{index}'
            if candidate:
                await candidate.finish()
            if publisher:
                await publisher.flush()
            await record.finish()
        except BaseException as error:
            timing('model.end', state='failed', error=type(error).__name__)
            if publisher:
                await publisher.fail(error, candidate.text if candidate else None)
            await record.finish(error)
            import httpx
            from app.integrations.models.transport import ProviderError
            if isinstance(error, (ProviderError, httpx.TransportError, asyncio.TimeoutError, json.JSONDecodeError)):
                raise safe_error(error) from None
            raise
        timing('model.end')
        output = sum((g.message.usage_metadata or {}).get('output_tokens', 0) or len(str(g.message.content)) + len(json.dumps(g.message.tool_calls, ensure_ascii=False)) for g in result.generations)
        context.output_tokens += output
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            if context.node_retry:
                from app.tasks.nodes.node_state import execution, save
                state = execution(job)
                state['outputTokens'] = state.get('outputTokens', 0) + output
                save(job, state)
            usage = await db.get(ModelUsage, usage_id)
            usage.output_tokens = output
        if context.model_purpose != 'assistant' and context.output_tokens > (32000 if context.node_retry else 8000):
            raise BudgetExceeded('模型响应超过本次输出限制，已停止后续处理')
        return result

    def _checked_chat_result(self, response, *, required_completion, internal_kind, timing):
        # Keep post-transport failures distinct and correlated with model.received;
        # exception messages can contain private model output and must not be logged.
        reason = 'framework_conversion'
        try:
            result = self._create_chat_result(response)
            reason = 'framework_tool_calls'
            if any(g.message.invalid_tool_calls for g in result.generations):
                raise ValueError('Incomplete tool call')
            reason = 'completion_validation'
            if self._completion_validator and not internal_kind:
                for generation in result.generations:
                    self._completion_validator(generation.message, required=required_completion)
            return result
        except (ValueError, TypeError, KeyError):
            from app.integrations.models.chat import invalid_response_diagnostic
            from app.integrations.models.transport import ProviderError
            invalid_response_diagnostic(response, reason, None, timing)
            raise ProviderError('invalid_response', '模型未返回完整有效的工具参数') from None

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        # Even framework streaming goes through the same reservation and complete
        # response validation; no tool is exposed from a partial wire stream.
        result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for generation in result.generations:
            message = generation.message
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content, tool_calls=message.tool_calls, usage_metadata=message.usage_metadata), generation_info=generation.generation_info)


def encode_result(result):
    return [{'content': g.message.content, 'id': g.message.id, 'tool_calls': g.message.tool_calls,
             'usage_metadata': g.message.usage_metadata} for g in result.generations]


def decode_result(value):
    return ChatResult(generations=[ChatGeneration(message=AIMessage(**item)) for item in value])
