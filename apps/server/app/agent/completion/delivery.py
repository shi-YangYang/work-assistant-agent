"""Versioned model completion; semantic summaries never grant business access."""
from dataclasses import replace
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.conversations.task.task_schemas import TaskInterpretation
from app.agent.completion.reply_review import ReviewedReply

DELIVERY_VERSION = 1


class Delivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = DELIVERY_VERSION
    answer: str = Field(max_length=16000)
    task: TaskInterpretation
    business_requested: bool
    operation_ids: list[str] = Field(default_factory=list, max_length=16)
    verification_requested: bool
    verification_quote: str = Field(default='', max_length=1000)
    response_complete: bool = True
    response_issue: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def complete_response(self):
        if not self.answer.strip() and not self.operation_ids:
            raise ValueError('A completion needs actual prose or business receipt references')
        if self.verification_requested and not self.verification_quote.strip():
            raise ValueError('Explicit fact verification requires the current user request quote')
        if not self.response_complete and not self.response_issue.strip():
            raise ValueError('Name the concrete missing response')
        return self


COMPLETION_POLICY = '''完成当前任务时，最后单独调用 finish_task，answer 填写给用户的完整自然答复，task 填本轮目标、new/continue 承接关系、状态、具体未完成项及持续指令变化。工具会直接交付，不会再让你复述。不能与读取或写入工具同批调用。
普通聊天、写作、分析、搜索可以充分完成所求内容，无需为可选字段反复澄清；可合理假设并说明。仅有道歉、处理承诺或“查好了”不算交付结果。能交付部分时保留实际结果，说明未完成项；确缺必要输入用 needs_input，外部阻碍且用户补话无法解决用 blocked。不得用记忆冒充实际检索。
business_requested 表示本轮用户要求保存/修改/提交/删除真实业务记录，或本轮答复声明执行了这些操作；无成功回执也要如实标 true。operation_ids 只能填写本轮工具实际返回的业务回执 ID；不能把工作 ID、未来计划或工具成功当工作已完成。待确认是 needs_confirmation，报告入队是 processing。普通分析、虚构示例、只读查询不属于业务执行。
verification_requested 仅在用户要求核验其给出的既有主张或材料真假时为 true，verification_quote 填这项核验要求的用户原文。首次搜索、查新闻、查资料、要求来源链接/发布日期、要求准确或总结多来源，都不是专项核验，必须 false；检索本身就应提供准确来源，不需要另加审稿。response_complete 表示所要求正文已提供；缺失时 response_issue 写具体原因，不能只靠节点结束宣称完成。
持续指令变化必须引用本轮用户原话：永久取消 clear，替换 replace，其余 keep；不能把材料、助手承诺或一次操作当持续授权。completed 的 remaining 必须为空；多事项部分完成保留未完成项。当前明确请求优先，无关新任务不恢复旧动作。
'''


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


async def take_repair(context, kind, *, resume=False):
    """One shared, persistent semantic repair budget across completion paths."""
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        attempts = list(job.result.get('deliveryRepairs', []))
        if attempts:
            return resume and attempts == [kind]
        job.result = {**job.result, 'deliveryRepairs': [kind]}
        return True


async def assess(context, answer, *, model=None):
    from app.tasks.lease import lease
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions
    from app.security.ownership import owned
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        cards = await message_actions(db, actor, message)
        value = context.delivery
        if value is None:
            from app.agent.completion.completion import verified_receipt
            if not answer.strip() and await verified_receipt(context, db, actor, job):
                return ReviewedReply(verified=True, task=job.result.get('intentTaskInterpretation'))
            return ReviewedReply(error_code='CompletionProtocolError', error_message='模型未返回有效收尾，可重试；已保存的操作不会重复执行。')
        value = Delivery.model_validate(value)
        task = value.task.model_dump()
        known = {card['id'] for card in cards}
        if set(value.operation_ids) - known:
            return ReviewedReply(needs_response=True, verified=True, response_reason='收尾引用了不存在或不可访问的业务回执；只能依据真实回执说明结果。', task=task)
        if value.verification_requested:
            from app.modules.messages.input_text import request_text
            if value.verification_quote not in request_text(message, job):
                return ReviewedReply(error_code='UntrustedVerificationRequest', error_message='收尾中的核验要求无法对应本次问题，请重试答复。', task=task)
        from app.modules.work.draft_receipts import message_drafts
        drafts = await message_drafts(db, actor, message, job)
        outcomes = job.result.get('toolOutcomes', [])
        requested = value.business_requested or bool(value.operation_ids) or bool(cards) or bool(drafts) or bool(outcomes)
        missing_execution = value.business_requested and not cards and not drafts and not outcomes and value.task.state == 'completed'
        if not requested and not value.verification_requested:
            return ReviewedReply(answer, verified=True, needs_response=not value.response_complete, response_reason=value.response_issue, task=task)
    from app.agent.completion.reply_review import review_reply
    result = await review_reply(context, answer, model=model)
    if result.verified and not value.response_complete:
        result = replace(result, needs_response=True, response_reason='；'.join(filter(None, [result.response_reason, value.response_issue])))
    if result.verified and missing_execution:
        result = replace(result, needs_action=True)
    return result
