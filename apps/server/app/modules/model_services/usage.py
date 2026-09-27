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
from sqlalchemy import and_, case, func, select, tuple_


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
            if failure and (failure.sent is False or failure.code == 'address' and failure.status is None):
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
    base = select(ModelUsage).where(ModelUsage.company_id == actor.company_id, ModelUsage.created_at >= lower, ModelUsage.created_at < upper)
    services = (await db.execute(base.with_only_columns(ModelUsage.service_id, ModelUsage.service_name).where(ModelUsage.service_id.is_not(None)).distinct(ModelUsage.service_id).order_by(ModelUsage.service_id, ModelUsage.created_at.desc(), ModelUsage.id.desc()))).all()
    model_query = base.with_only_columns(ModelUsage.model_name).where(ModelUsage.model_name.is_not(None), ModelUsage.model_name != '')
    if service:
        model_query = model_query.where(ModelUsage.service_id == service)
    models = list((await db.scalars(model_query.distinct().order_by(ModelUsage.model_name))).all())
    query = base
    for column, value in ((ModelUsage.service_id, service), (ModelUsage.model_name, model), (ModelUsage.kind, purpose)):
        if value:
            query = query.where(column == value)
    cutoff = now() - timedelta(minutes=2)
    effective = case((and_(ModelUsage.status == 'running', ModelUsage.started_at < cutoff), 'unknown'), else_=ModelUsage.status)
    started = ModelUsage.started_at.is_not(None)
    states = ('reserved', 'running', 'succeeded', 'failed', 'unknown', 'legacy', 'not_sent')
    counts = [func.count().filter(effective == state).label(state) for state in states]
    aggregates = [
        func.count().filter(started).label('calls'),
        func.avg(ModelUsage.elapsed_ms).filter(started).label('average'),
        func.count(ModelUsage.elapsed_ms).filter(started).label('durationKnown'),
        func.coalesce(func.sum(ModelUsage.actual_input_tokens).filter(started), 0).label('inputTokens'),
        func.coalesce(func.sum(ModelUsage.actual_output_tokens).filter(started), 0).label('outputTokens'),
        func.count(ModelUsage.actual_input_tokens).filter(started).label('inputKnown'),
        func.count(ModelUsage.actual_output_tokens).filter(started).label('outputKnown'),
    ]
    values = (await db.execute(query.with_only_columns(*counts, *aggregates))).one()._mapping
    resolved = values['succeeded'] + values['failed']
    summary = {key: values[key] for key in ('calls', 'durationKnown', 'inputTokens', 'outputTokens', 'inputKnown', 'outputKnown')}
    summary.update(states={state: values[state] for state in states}, successRate=values['succeeded'] / resolved if resolved else None, averageMs=round(values['average']) if values['average'] is not None else None)
    if cursor:
        query = query.where(tuple_(ModelUsage.created_at, ModelUsage.id) < cursor_decode(cursor))
    rows = (await db.execute(query.add_columns(effective.label('effective')).order_by(ModelUsage.created_at.desc(), ModelUsage.id.desc()).limit(limit + 1))).all()
    return {'range': date_range, 'summary': summary, 'services': [{'id': key, 'name': name} for key, name in services], 'models': models, 'items': [{**dto(row), 'state': state} for row, state in rows[:limit]], 'nextCursor': cursor_encode(rows[limit - 1][0].created_at, rows[limit - 1][0].id) if len(rows) > limit else None}
