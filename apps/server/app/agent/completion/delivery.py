"""Versioned model completion; semantic summaries never grant business access."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.conversations.task.task_schemas import TaskInterpretation
from app.agent.completion.review.reply_review import ReviewedReply
from app.agent.completion.answer_length import AnswerLength
from pydantic.json_schema import SkipJsonSchema

DELIVERY_VERSION = 1


class Delivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1, 2] = DELIVERY_VERSION
    answer: str
    task: TaskInterpretation
    business_requested: bool
    operation_ids: list[str] = Field(default_factory=list, max_length=16)
    verification_requested: bool
    verification_quote: str = Field(default='', max_length=1000)
    response_complete: bool = True
    response_issue: str = Field(default='', max_length=500)
    answer_length: SkipJsonSchema[AnswerLength | None] = None

    @model_validator(mode='after')
    def complete_response(self):
        if not self.answer.strip() and not self.operation_ids:
            raise ValueError('A completion needs actual prose or business receipt references')
        if self.verification_requested and not self.verification_quote.strip():
            raise ValueError('Explicit fact verification requires the current user request quote')
        if not self.response_complete and not self.response_issue.strip():
            raise ValueError('Name the concrete missing response')
        return self


PUBLIC_REPLY_POLICY = '''用户正文只回答用户原请求。服务端校验、材料读取范围、工具收尾字段、内部回执编号和修复指令是控制信息，不是用户的新问题，也不是要展示的内容；材料来源保留引用标记。内部纠错时直接交付修正后的完整结果；不要复述字段名、参数误标、核对过程或未交付草稿，不为内部修复另写道歉或处理报告。仅元数据有误时保留正确正文。真实失败或限制仍应说明对用户任务的影响、已完成部分与必要下一步，不能为了隐藏内部流程而隐瞒失败。用户明确询问产品机制时可以解释可公开的行为。\n'''


def from_messages(messages):
    """Only the guarded graph's last tool completion is a completion receipt."""
    from langchain_core.messages import AIMessage, ToolMessage
    batch = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not batch or len(batch.tool_calls) != 1 or batch.tool_calls[0]['name'] != 'finish_task':
        return None
    call = batch.tool_calls[0]
    result = next((m for m in reversed(messages) if isinstance(m, ToolMessage) and m.tool_call_id == call['id']), None)
    if not result or result.status == 'error':
        return None
    try:
        return Delivery.model_validate_json(result.content)
    except (ValueError, TypeError):
        return None


def validate_completion_response(message, *, required=False):
    """Reject malformed terminal arguments before a model node caches success."""
    calls = message.tool_calls
    if not calls and message.text.strip():
        from app.agent.completion.prose import parse_header
        parse_header(message.text, complete=True)
    if required and (len(calls) != 1 or calls[0]['name'] != 'finish_task'):
        raise ValueError('Expected the single required completion tool')
    if any(call['name'] == 'finish_task' for call in calls) and len(calls) != 1:
        raise ValueError('Completion must be the only tool')
    for call in calls:
        if call['name'] == 'finish_task':
            arguments = call['args']
            Delivery.model_validate({**arguments, 'operation_ids': arguments.get('operation_ids') or []})


async def completion_reference_error(context, operation_ids, *, verification_requested=False, verification_quote=''):
    """Reject wrong receipt metadata while the bounded protocol repair can fix it."""
    if not operation_ids and not verification_requested:
        return None
    from app.tasks.lease import lease
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions
    from app.security.ownership import owned
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        known = {card['id'] for card in await message_actions(db, actor, message)}
        from app.modules.messages.input.input_text import request_text
        current_request = request_text(message, job)
    if set(operation_ids or []) - known:
        return ('收尾引用了本轮业务回执以外的 ID，不能沿用此前消息的回执。私人成果、生成文件和沙盒执行 ID 都不是业务回执。'
                '请依据本轮真实结果直接交付正文，区分此前操作与本轮查询；保留已生成文件，不重做工具或业务操作。'
                '本轮可用业务回执 ID：' + ', '.join(sorted(known)))
    if verification_requested and (not isinstance(verification_quote, str) or not verification_quote.strip() or verification_quote not in current_request):
        return ('核验声明引用的内容不是当前用户请求的逐字原文，不能沿用以前消息或助手改写。'
                '请按本轮实际请求直接交付正文，保留已有实测证据，不重做工具或业务操作。')
    return None


async def take_repair(context, kind, *, resume=False):
    """One protocol repair plus one shared semantic repair, persisted across retries."""
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        attempts = list(job.result.get('deliveryRepairs', []))
        group = [item for item in attempts if (item == 'protocol') == (kind == 'protocol')]
        if group:
            return resume and group == [kind]
        job.result = {**job.result, 'deliveryRepairs': [*attempts, kind]}
        return True


async def assess(context, answer, *, model=None):
    """Local delivery checks only; model is retained for caller compatibility."""
    from app.tasks.lease import lease
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions
    from app.security.ownership import owned
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        cards = await message_actions(db, actor, message)
        from app.tasks.feedback.public import prose
        from app.modules.messages.input.input_text import request_text
        answer = prose(answer, job, request_text(message, job))
        value = context.delivery
        if value is None:
            from app.agent.completion.completion import verified_receipt
            if not answer.strip() and await verified_receipt(context, db, actor, job):
                return ReviewedReply(verified=True, task=job.result.get('intentTaskInterpretation'))
            return ReviewedReply(error_code='CompletionProtocolError', error_message='模型未返回有效收尾，可重试；已保存的操作不会重复执行。')
        value = Delivery.model_validate(value)
        from app.agent.completion.prose import task_for
        task = task_for(job, value.task.model_dump()).model_dump()
        from app.tasks.feedback.work_requirements import task_with_remaining
        task = task_with_remaining(job, cards, task)
        from app.tasks.feedback.report_waits import normalize as normalize_report_waits
        task = normalize_report_waits(job, cards, task, clock=getattr(context, 'request_clock', ''))
        known = {card['id'] for card in cards}
        if set(value.operation_ids) - known:
            return ReviewedReply(needs_response=True, verified=True, response_reason='收尾引用了不存在或不可访问的业务回执；只能依据真实回执说明结果。', task=task)
        if value.verification_requested:
            from app.modules.messages.input.input_text import request_text
            if value.verification_quote not in request_text(message, job):
                return ReviewedReply(error_code='UntrustedVerificationRequest', error_message='收尾中的核验要求无法对应本次问题，请重试答复。', task=task)
        from app.modules.work.drafts.draft_receipts import message_drafts
        drafts = await message_drafts(db, actor, message, job)
        outcomes = job.result.get('toolOutcomes', [])
        missing_execution = value.business_requested and not cards and not drafts and not outcomes and task['state'] == 'completed'
        response_issue = value.response_issue if not value.response_complete else ''
        # Completion validates protocol and actual receipts, never asks a second
        # model to grade the prose. Explicit verification is part of the main
        # agent task; numeric content and observed tool evidence add no calls.
        # Historical review caches cannot trigger repairs after this change.
        return ReviewedReply('' if missing_execution else answer, verified=True,
            execution_claims=missing_execution, needs_action=missing_execution,
            needs_response=bool(response_issue), response_reason=response_issue, task=task)


async def delivery_for(context, raw, *, pending_task=None):
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions
    from app.security.ownership import owned
    from app.tasks.lease import lease
    from app.agent.completion.prose import parse_header, task_for
    answer, unfinished, _ = parse_header(raw, complete=True)
    if not answer.strip():
        raise ValueError('模型未返回有效正文')
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        from app.tasks.feedback.public import prose
        from app.modules.messages.input.input_text import request_text
        answer = prose(answer, job, request_text(message, job))
        cards = await message_actions(db, actor, message)
        waiting = (unfinished or {}).get('waitingOperationIds', [])
        if waiting:
            from app.tasks.feedback.report_waits import invalid_waiting_ids
            if invalid_waiting_ids(job, cards, waiting):
                # Keep the answer and real receipts. An unbound wait cannot
                # become success or trigger another model call to repair it.
                unfinished = {**unfinished, 'state': 'blocked', 'remaining': [
                    *unfinished.get('remaining', []), '报告等待未能对应当前任务的有效回执']}
        task = job.result.get('explicitTaskContext') or job.result.get('intentTaskInterpretation') or {}
        for extra in (pending_task, unfinished):
            if not extra or 'state' not in extra:
                continue
            remaining = list(dict.fromkeys([*task.get('remaining', []), *extra.get('remaining', [])]))
            state = task.get('state', 'completed')
            if state == 'completed' or extra.get('state') == 'blocked':
                state = extra['state']
            task = {**task, 'state': state,
                    'remaining': remaining[:7] + ['；'.join(remaining[7:])] if len(remaining) > 8 else remaining}
        return Delivery(version=2, answer=answer, task=task_for(job, task),
                        business_requested=bool(cards or job.result.get('explicitBusinessRequest')),
                        operation_ids=[card['id'] for card in cards], verification_requested=False)
