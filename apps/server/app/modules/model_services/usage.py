import asyncio
from datetime import timedelta
from fastapi import HTTPException
from app.core.pagination import cursor_decode, cursor_encode
from app.core.periods import period_range
from app.db.base import now
from app.integrations.models.chat import token_usage
from app.integrations.models.transport import safe_error
from app.modules.members.models import Company
from app.modules.model_services.models import ModelUsage
from sqlalchemy import select


def usage_fields(choice=None, *, attempt=None, fence=None):
    choice = choice or {}
    return dict(status='reserved', service_id=choice.get('serviceId'), service_name=choice.get('name'), model_name=choice.get('model'), job_attempt=attempt, job_fence=fence)


class RequestRecord:
    def __init__(self, sessions, identifier):
        self.sessions, self.identifier = sessions, identifier

    async def event(self, event, value=None):
        async with self.sessions.begin() as db:
            row = await db.scalar(select(ModelUsage).where(ModelUsage.id == self.identifier).with_for_update())
            if event == 'started' and row.status == 'reserved':
                row.status, row.started_at = 'running', now()
            if event == 'usage':
                usage = token_usage(value) or {}
                if 'prompt_tokens' in usage:
                    row.actual_input_tokens = usage['prompt_tokens']
                if 'completion_tokens' in usage:
                    row.actual_output_tokens = usage['completion_tokens']

    async def run(self, request):
        try:
            response = await request(self.event)
        except BaseException as error:
            await self.finish(error)
            raise
        await self.finish()
        return response

    async def finish(self, error=None):
        async with self.sessions.begin() as db:
            row = await db.scalar(select(ModelUsage).where(ModelUsage.id == self.identifier).with_for_update())
            if row.status not in ('reserved', 'running'):
                return
            row.finished_at = now()
            failure = safe_error(error) if error is not None else None
            # Address validation without an HTTP status rejects before sending;
            # redirects carry a status and remain actual, failed requests.
            if failure and failure.code == 'address' and failure.status is None:
                row.started_at = None
            row.elapsed_ms = max(0, round((row.finished_at - row.started_at).total_seconds() * 1000)) if row.started_at else None
            if error is None:
                row.status = 'succeeded'
            else:
                uncertain = isinstance(error, (asyncio.CancelledError, HTTPException)) or type(error).__name__ in ('LostLease', 'InputChanged') or failure.code in ('timeout', 'interrupted') or (failure.code == 'network' and failure.status is None)
                row.status = 'unknown' if row.started_at and uncertain else 'failed' if row.started_at else 'not_sent'
                row.error_code, row.error_message = failure.code, str(failure)


async def interrupt_usage(db, job):
    rows = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id, ModelUsage.status.in_(('reserved', 'running'))).with_for_update())).all()
    for row in rows:
        row.status = 'unknown' if row.started_at else 'not_sent'
        row.finished_at, row.error_code, row.error_message = now(), 'interrupted', '处理进程中断，请求结果未知' if row.started_at else '请求尚未发出'


def dto(row):
    return {'id': row.id, 'serviceId': row.service_id, 'service': row.service_name, 'model': row.model_name, 'purpose': row.kind, 'state': row.status, 'startedAt': row.started_at.isoformat() if row.started_at else None, 'createdAt': row.created_at.isoformat(), 'elapsedMs': row.elapsed_ms, 'inputTokens': row.actual_input_tokens, 'outputTokens': row.actual_output_tokens, 'errorCode': row.error_code, 'error': row.error_message}


async def usage_page(db, actor, *, period='this_week', start=None, end=None, service='', model='', purpose='', cursor=None, limit=20):
    company = await db.get(Company, actor.company_id)
    lower, upper, date_range = period_range(company, period, start, end)
    query = select(ModelUsage).where(ModelUsage.company_id == actor.company_id, ModelUsage.created_at >= lower, ModelUsage.created_at < upper)
    all_rows = list((await db.scalars(query.order_by(ModelUsage.created_at.desc(), ModelUsage.id.desc()))).all())
    services = {row.service_id: row.service_name for row in reversed(all_rows) if row.service_id}
    models = sorted({row.model_name for row in all_rows if row.model_name and (not service or row.service_id == service)})
    rows = [row for row in all_rows if (not service or row.service_id == service) and (not model or row.model_name == model) and (not purpose or row.kind == purpose)]
    def effective(row):
        # A dead API probe cannot be recovered by a job lease. Its 60s request
        # limit has elapsed; report unknown without inventing a failure/result.
        return 'unknown' if row.status == 'running' and row.started_at and row.started_at < now() - timedelta(minutes=2) else row.status
    states = {key: sum(effective(row) == key for row in rows) for key in ('reserved','running','succeeded','failed','unknown','legacy','not_sent')}
    actual = [row for row in rows if row.started_at is not None]
    resolved = states['succeeded'] + states['failed']
    elapsed = [row.elapsed_ms for row in actual if row.elapsed_ms is not None]
    summary = {'calls': len(actual), 'successRate': states['succeeded'] / resolved if resolved else None, 'states': states, 'averageMs': round(sum(elapsed) / len(elapsed)) if elapsed else None, 'durationKnown':len(elapsed), 'inputTokens':sum(row.actual_input_tokens for row in actual if row.actual_input_tokens is not None), 'outputTokens':sum(row.actual_output_tokens for row in actual if row.actual_output_tokens is not None), 'inputKnown':sum(row.actual_input_tokens is not None for row in actual), 'outputKnown':sum(row.actual_output_tokens is not None for row in actual)}
    if cursor:
        boundary = cursor_decode(cursor)
        rows = [row for row in rows if (row.created_at, row.id) < boundary]
    return {'range':date_range, 'summary':summary, 'services':[{'id':key,'name':value} for key,value in services.items()], 'models':models, 'items':[{**dto(row), 'state':effective(row)} for row in rows[:limit]], 'nextCursor':cursor_encode(rows[limit-1].created_at,rows[limit-1].id) if len(rows)>limit else None}
