"""Targeted business/verification issues, never a general prose editor."""
import json
import logging
from dataclasses import dataclass
from typing import Literal
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from app.agent.model import BoundedChatModel, approximate_tokens
from app.core.digests import digest
from app.integrations.models.transport import ProviderError
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.context import InputChanged, LostLease
from app.tasks.lease import lease

log = logging.getLogger('paa.company')
REVIEW_TASK = 'business_reply_review'
REVIEW_VERSION = 30


@dataclass(frozen=True)
class ReviewedReply:
    text: str = ''
    execution_claims: bool = False
    verified: bool = False
    error_code: str = ''
    error_message: str = ''
    needs_action: bool = False
    needs_response: bool = False
    response_reason: str = ''
    task: dict | None = None


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['execution', 'fact', 'missing_action', 'missing_response']
    reason: str = Field(min_length=1, max_length=500)
    quote: str = Field(default='', max_length=16000)
    evidence: list[int] = Field(default_factory=list, max_length=32)
    receipt_ids: list[str] = Field(default_factory=list, max_length=16)


class ReplyVerdict(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issues: list[ReviewIssue] = Field(max_length=16)


class ReviewFormatError(ValueError):
    pass


def check_issues(answer, raw, evidence, actions=(), task=None, drafts=()):
    try:
        verdict = ReplyVerdict.model_validate_json(raw.strip().removeprefix('```json').removesuffix('```').strip())
    except (ValueError, TypeError) as error:
        raise ReviewFormatError('Invalid issue review schema') from error
    evidence_ids = {item['id'] for item in evidence}
    receipt_ids = {item['id'] for item in actions}
    text = answer
    for issue in verdict.issues:
        if set(issue.evidence) - evidence_ids or set(issue.receipt_ids) - receipt_ids:
            raise ReviewFormatError('Review cites evidence outside the current task')
        if issue.quote and issue.quote not in answer:
            raise ReviewFormatError('Review quote is not an exact part of the answer')
        if issue.kind in ('execution', 'fact') and not issue.quote:
            raise ReviewFormatError('A disputed statement needs its exact quote')
        if issue.kind in ('execution', 'fact'):
            text = text.replace(issue.quote, '')
    unresolved_execution = not actions and not drafts and not text.strip() and any(issue.kind == 'execution' for issue in verdict.issues)
    needs_response = unresolved_execution or any(issue.kind in ('fact', 'missing_response') for issue in verdict.issues)
    reasons = '；'.join(issue.reason for issue in verdict.issues if issue.kind in ('fact', 'missing_response'))
    if unresolved_execution:
        reasons = '；'.join(filter(None, [reasons, '没有实际业务执行结果，必须说明未完成的具体事项，不能只给空答复或声称完成。']))
    return ReviewedReply(text.strip(), execution_claims=any(issue.kind == 'execution' for issue in verdict.issues),
        verified=True, needs_action=any(issue.kind == 'missing_action' for issue in verdict.issues),
        needs_response=needs_response, response_reason=reasons, task=task)


async def review_reply(context, answer, *, model=None):
    from app.agent.conversation_context import request_text, conversation_references
    from app.agent.task_context import projection, TASK_POLICY
    from app.agent.policies import role_capabilities, REPORT_WRITING_POLICY
    from app.modules.operations.receipts import message_actions
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        if not answer.strip():
            from app.agent.completion import verified_receipt
            if await verified_receipt(context, db, actor, job):
                return ReviewedReply(verified=True, task=job.result.get('intentTaskInterpretation'))
        from app.modules.work.draft_receipts import message_drafts
        drafts = await message_drafts(db, actor, message, job)
        draft_values = [{'id': draft.id, 'status': draft.status} for draft in drafts]
        task = (context.delivery or {}).get('task') or job.result.get('intentTaskInterpretation')
        payload = {'task': REVIEW_TASK, 'version': REVIEW_VERSION,
            'currentUserText': request_text(message, job), 'answer': answer,
            'delivery': context.delivery, 'conversationTask': await projection(db, actor, job, message, context),
            'roleCapabilities': role_capabilities(actor.role),
            'conversationForReferenceOnly': await conversation_references(db, actor, job, message, context=context),
            'currentActions': await message_actions(db, actor, message), 'currentDrafts': draft_values,
            'toolEvidence': context.reply_evidence, 'toolOutcomes': job.result.get('toolOutcomes', []),
            'requestClock': getattr(context, 'request_clock', '')}
        fingerprint = digest(payload)
        cached = job.result.get('replyReview', {})
        if cached.get('digest') == fingerprint:
            try:
                return check_issues(answer, cached['verdict'], context.reply_evidence, payload['currentActions'], task, draft_values)
            except (ValueError, KeyError):
                pass
    prompt = [SystemMessage(content=TASK_POLICY + '\n' + REPORT_WRITING_POLICY + '''
你只核对具体业务执行和用户明确要求核实的事实。返回 JSON {"issues":[]}，无问题即空数组，不为普通建议、人设、比喻、解释长度或“额外内容”编辑正文，不逐段分类。不要改写任务目标或新增授权。
问题结构 {"kind":"execution|fact|missing_action|missing_response","reason":"具体冲突或遗漏","quote":"有问题的原文完整片段","evidence":[],"receipt_ids":[]}。引用必须是当前工具证据 ID 或回执 ID；不能编造。execution/fact 必须给出逐字原文 quote，其余 quote 留空。仅指出有依据的具体问题，无来源的推断不能推翻真实回执。
execution：原文声称本轮已保存/删除/提交但回执不成立，或把入队、待确认、保存成功说成工作完成。只是回答已有报告是否提交，或虚构样例、计划和比喻不是本轮执行声明。当前工作状态、实际改动字段以 currentActions.details/changedFields 为准。
fact：业务变更说明与真实字段不符，或用户明确要求核验的事实与本轮来源矛盾。标明已知假设和未核实部分不是错误，不因未联网就否定一般知识、分析或建议。
missing_action：对照原用户请求，有明确已授权且信息足够的操作完全没调用工具，即使其余操作已完成也指出。明确失败、缺信息、权限拒绝、确认卡或报告处理中不是漏调用，不重新触发同一阻碍。
missing_response：用户还要求的解释/分析等实质内容缺失，仅有道歉、承诺或工具回执不能替代。确需用户补充、权限拒绝或处理中可如实说明；不要求额外建议。保留其它无争议内容。不要把系统问题归咎于用户没说清楚。
'''), HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':')))]
    try:
        from app.agent.context_usage import ensure_input
        ensure_input(context, approximate_tokens(prompt), 2000)
        judge = model
        if judge is None:
            choice = (context.model_binding or {}).get('assistant') or {}
            judge = BoundedChatModel(model=choice.get('model', 'unconfigured'), api_key='server-managed', max_retries=0, timeout=60, max_tokens=2000, streaming=False, use_responses_api=False, stream_usage=False)
            judge._run_context = context
            judge._verification = True
        from app.tasks.node_execution import execute_node
        invalid_format = False
        def parse(response):
            nonlocal invalid_format
            try:
                check_issues(answer, response.text, context.reply_evidence, payload['currentActions'], task, draft_values)
            except ReviewFormatError as error:
                invalid_format = True
                raise ProviderError('invalid_response', '专项核对未返回完整有效结果') from error
            return response.text
        if isinstance(judge, BoundedChatModel):
            judge._response_validator = parse
        async def check():
            messages = [*prompt, HumanMessage(content='上次返回不符合问题契约。仅返回 issues 数组，每项 kind 必须为 execution/fact/missing_action/missing_response，reason 必填；execution/fact 的 quote 必须逐字来自候选正文，证据及回执 ID 只能用本轮实际值。')] if invalid_format else prompt
            return parse(await judge.ainvoke(messages))
        raw = await execute_node(context, identity=fingerprint, kind='review', label='核对操作结果中' if not (context.delivery or {}).get('verification_requested') else '核验事实中', operation=check)
        reviewed = check_issues(answer, raw, context.reply_evidence, payload['currentActions'], task, draft_values)
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            job.result = {**job.result, 'replyReview': {'digest': fingerprint, 'verdict': raw}}
        return reviewed
    except (LostLease, InputChanged, HTTPException):
        raise
    except Exception as error:
        log.info('job=%s reply_review_failure=%s', context.job_id, type(error).__name__)
        from app.tasks.retry import NodeFailed
        cause = error.__cause__ if isinstance(error, NodeFailed) and error.__cause__ else error
        message = str(error) if isinstance(error, NodeFailed) or isinstance(error, ProviderError) else ''
        return ReviewedReply(error_code=type(cause).__name__, error_message=message, task=task)
