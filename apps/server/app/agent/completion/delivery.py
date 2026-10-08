"""Versioned model completion; semantic summaries never grant business access."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.conversations.task.task_schemas import TaskInterpretation
from app.agent.completion.reply_review import ReviewedReply
from app.agent.completion.limits import MAX_ANSWER_LENGTH
from app.agent.completion.answer_length import AnswerLength, LENGTH_POLICY, check_length

DELIVERY_VERSION = 1


class Delivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = DELIVERY_VERSION
    answer: str = Field(max_length=MAX_ANSWER_LENGTH)
    task: TaskInterpretation
    business_requested: bool
    operation_ids: list[str] = Field(default_factory=list, max_length=16)
    verification_requested: bool
    verification_quote: str = Field(default='', max_length=1000)
    response_complete: bool = True
    response_issue: str = Field(default='', max_length=500)
    answer_length: AnswerLength | None = None

    @model_validator(mode='after')
    def complete_response(self):
        if not self.answer.strip() and not self.operation_ids:
            raise ValueError('A completion needs actual prose or business receipt references')
        if self.verification_requested and not self.verification_quote.strip():
            raise ValueError('Explicit fact verification requires the current user request quote')
        if not self.response_complete and not self.response_issue.strip():
            raise ValueError('Name the concrete missing response')
        return self


PUBLIC_REPLY_POLICY = '''用户正文只回答用户原请求。服务端校验、工具收尾字段、内部回执编号和修复指令是控制信息，不是用户的新问题，也不是要展示的内容。内部纠错时直接交付修正后的完整结果；不要复述字段名、参数误标、核对过程或未交付草稿，不为内部修复另写道歉或处理报告。仅元数据有误时保留正确正文。真实失败或限制仍应说明对用户任务的影响、已完成部分与必要下一步，不能为了隐藏内部流程而隐瞒失败。用户明确询问产品机制时可以解释可公开的行为。\n'''


COMPLETION_POLICY = PUBLIC_REPLY_POLICY + LENGTH_POLICY + '''完成当前任务时，最后单独调用 finish_task，answer 填写给用户的完整自然答复，task 填本轮目标、new/continue 承接关系、状态、具体未完成项及持续指令变化。工具会直接交付，不会再让你复述。不能与读取或写入工具同批调用。只有 answer 会展示为本轮最终正文；过程草稿和同次工具调用消息的 content 都不代表已向用户交付。所需解释、表格和代码必须完整放入 answer，不能用“已在对话中给出”的总结代替。
普通聊天、写作、分析、搜索可以充分完成所求内容，无需为可选字段反复澄清；可合理假设并说明。仅有道歉、处理承诺或“查好了”不算交付结果。能交付部分时保留实际结果，说明未完成项；确缺必要输入用 needs_input，权限、产品能力或外部阻碍且用户补话无法解决用 blocked，不要把已明确的拒绝标成 completed 或 needs_input；说明具体限制即可，不要求用户反复确认无权操作。不得用记忆冒充实际检索。
完成状态针对本轮交付物：用户改为索要所需资料清单、提问措辞或计划时，交付这些内容就完成本轮；清单中将来要收集的信息不是生成清单所需的输入。不要把上一轮尚不能核实的事项继承为本轮 remaining。只有缺失信息确实阻止当前要求的交付时才 needs_input；正文中的可选追问不改变完成状态。
business_requested 表示本轮用户要求保存/修改/提交/删除真实业务记录，或本轮答复声明执行了这些操作；无成功回执也要如实标 true。operation_ids 只能填写本轮工具实际返回的业务回执 ID；不能把工作 ID、未来计划或工具成功当工作已完成。私人成果和生成文件不属于公司业务记录，deliverable_id、文件 ID 和沙盒执行 ID 都不能填入 operation_ids；仅要求生成文件时 business_requested=false、operation_ids=[]。待确认是 needs_confirmation，报告入队是 processing。普通分析、虚构示例、只读查询不属于业务执行。
verification_requested 仅在用户要求核验其给出的既有主张或材料真假时为 true，verification_quote 填这项核验要求的用户原文。首次搜索、查新闻、查资料、要求来源链接/发布日期、要求准确或总结多来源，都不是用户专项核验，必须 false；核验属于主任务，应使用已有来源或必要工具完成，再直接交付结论；服务端不会追加另一轮模型审稿。答案应与本轮实际读取、执行结果一致。response_complete 表示所要求正文已提供；缺失时 response_issue 写具体原因，不能只靠节点结束宣称完成。
verification_quote 必须引用本轮实际要求执行核验的完整指令，不能只截取提到核验的主题词；索要核验所需资料、拟一段核验请求或转述此前核验，不等于本轮要求再次核验。
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


def reference_repair_needed(messages, job_id):
    """Allow feedback on the first terminal call after plain-text recovery."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    repair = next((index for index in range(len(messages) - 1, -1, -1)
                   if isinstance(messages[index], HumanMessage)), None)
    if repair is None or messages[repair].id != f'delivery-repair:{job_id}':
        return False
    original = next((message for message in reversed(messages[:repair]) if isinstance(message, AIMessage)), None)
    batch = next((message for message in reversed(messages[repair + 1:]) if isinstance(message, AIMessage)), None)
    if not original or original.tool_calls or not batch or len(batch.tool_calls) != 1 or batch.tool_calls[0]['name'] != 'finish_task':
        return False
    output = next((message for message in reversed(messages) if isinstance(message, ToolMessage)
                   and message.tool_call_id == batch.tool_calls[0]['id']), None)
    return bool(output and output.status == 'error' and output.additional_kwargs.get('completion_reference_error'))


def validate_completion_response(message, *, required=False):
    """Reject malformed terminal arguments before a model node caches success."""
    calls = message.tool_calls
    if required and (len(calls) != 1 or calls[0]['name'] != 'finish_task'):
        raise ValueError('Expected the single required completion tool')
    if any(call['name'] == 'finish_task' for call in calls) and len(calls) != 1:
        raise ValueError('Completion must be the only tool')
    for call in calls:
        if call['name'] == 'finish_task':
            arguments = call['args']
            Delivery.model_validate({**arguments, 'operation_ids': arguments.get('operation_ids') or []})


async def completion_reference_error(context, operation_ids, *, verification_requested=False, verification_quote='', answer_length=None, answer=''):
    """Reject wrong receipt metadata while the bounded protocol repair can fix it."""
    if not operation_ids and not verification_requested and not answer_length:
        return None
    from app.tasks.lease import lease
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions
    from app.security.ownership import owned
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        known = {card['id'] for card in await message_actions(db, actor, message)}
        from app.modules.messages.input_text import request_text
        current_request = request_text(message, job)
    if set(operation_ids or []) - known:
        return ('operation_ids 引用了本轮业务回执以外的 ID，不能沿用此前消息的回执。私人成果、生成文件和沙盒执行 ID 都不是业务回执；'
                '本轮仅查询或交付文件时 business_requested=false、operation_ids=[]。答复应区分此前操作与本轮查询，'
                '保留已生成文件和答复，不要重新执行工具。'
                '本轮可用业务回执 ID：' + ', '.join(sorted(known)))
    if verification_requested and (not isinstance(verification_quote, str) or not verification_quote.strip() or verification_quote not in current_request):
        return ('verification_quote 不是当前用户请求的逐字原文，不能沿用以前消息或助手改写。'
                '当前确有核验要求时，保留 verification_requested=true 并引用当前原话；'
                '否则改为 false 并清空 verification_quote。只修正收尾字段，保留已有正文和实测证据，不重做工具或业务操作。')
    if answer_length:
        from app.agent.completion.answer_length import validate_reference
        try:
            validate_reference(AnswerLength.model_validate(answer_length), answer, current_request)
        except ValueError as error:
            return 'answer_length 引用无效：' + str(error) + '请按本轮实际长度要求修正收尾引用，不重做工具或业务操作；不要删除真实存在的长度约束。'
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
        missing_execution = value.business_requested and not cards and not drafts and not outcomes and value.task.state == 'completed'
        from app.modules.messages.input_text import request_text
        length_issue = check_length(value.answer_length, answer, request_text(message, job))
        response_issue = '；'.join(filter(None, [value.response_issue if not value.response_complete else '', length_issue]))
        # Completion validates protocol and actual receipts, never asks a second
        # model to grade the prose. Explicit verification is part of the main
        # agent task; numeric content and observed tool evidence add no calls.
        # Historical review caches cannot trigger repairs after this change.
        return ReviewedReply('' if missing_execution else answer, verified=True,
            execution_claims=missing_execution, needs_action=missing_execution,
            needs_response=bool(response_issue), response_reason=response_issue, task=task)
