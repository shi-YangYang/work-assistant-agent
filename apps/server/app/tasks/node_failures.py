"""Application error classification. Never inspect free-form model/tool prose."""
import asyncio
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from app.integrations.models.transport import ProviderError
from app.tasks.context import BudgetExceeded, InputChanged, LostLease
from app.tasks.retry import Failure, NodeFailed


def classify(error):
    if isinstance(error, NodeFailed):
        return Failure('child_failed', '内部核对未完成，请重试失败步骤')
    if isinstance(error, (LostLease, InputChanged, asyncio.CancelledError)):
        return Failure('input_changed' if isinstance(error, InputChanged) else 'cancelled',
                       str(error) or '处理已停止，任务或权限已变化', cancelled=True)
    if isinstance(error, BudgetExceeded):
        return Failure('budget', str(error))
    if isinstance(error, ProviderError):
        retryable = error.code in ('timeout', 'interrupted', 'invalid_response', 'rate_limit') or error.code == 'network' and (error.status is None or error.status in (408, 500, 502, 503, 504))
        return Failure(error.code, str(error), retryable, error.retry_after)
    if isinstance(error, (asyncio.TimeoutError, httpx.TransportError)):
        return Failure('timeout', '模型暂未响应', True)
    if isinstance(error, DBAPIError):
        code = getattr(error.orig, 'sqlstate', None)
        return Failure('transaction' if code in ('40001', '40P01') else 'database',
                       '数据保存暂时冲突' if code in ('40001', '40P01') else '数据操作未完成，请核对后重试', code in ('40001', '40P01'))
    if isinstance(error, HTTPException):
        detail = error.detail if isinstance(error.detail, dict) else {}
        revoked = detail.get('code') == 'business_access_changed'
        return Failure('permission' if error.status_code in (401, 403) else 'business',
                       detail.get('message', '操作未执行，请核对输入与权限'), cancelled=revoked)
    if isinstance(error, (ValueError, ValidationError)):
        return Failure('invalid_input', '输入或配置无效，请核对后重试')
    return Failure('unknown', '此步骤未完成，请重试或联系管理员')
