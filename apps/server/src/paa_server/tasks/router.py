import hashlib
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.http.dependencies import AUTH, DB, SESSIONS, SETTINGS
from paa_server.modules.attachments.models import Attachment
from paa_server.modules.auth.sessions import COOKIE
from paa_server.modules.messages.service import active_message
from paa_server.modules.model_services.schemas import RetryJob
from paa_server.modules.reports.models import Report
from paa_server.security.access import require as business_require
from paa_server.security.ownership import owned
from paa_server.tasks.models import Job
from paa_server.tasks.serializers import job_dto

router = APIRouter()


@router.get('/api/v1/jobs/{identifier}')
async def get_job(identifier: str, actor=AUTH, db=DB):
    item = await owned(db, Job, identifier, actor)
    await business_require(db, actor, item.access)
    return job_dto(item)


@router.get('/api/v1/jobs/{identifier}/feedback')
async def job_feedback(identifier: str, request: Request, actor=AUTH, sessions=SESSIONS):
    from paa_server.tasks.feedback import snapshot
    return await snapshot(sessions, hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest(), identifier)


@router.get('/api/v1/jobs/{identifier}/events')
async def job_events(identifier: str, request: Request, actor=AUTH, settings=SETTINGS, sessions=SESSIONS):
    from paa_server.tasks.feedback import snapshot, events
    if request.headers.get('origin') not in (None, settings.web_origin) or request.headers.get('sec-fetch-site') == 'cross-site':
        problem(403, '请求来源不被允许')
    token_hash = hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest()
    await snapshot(sessions, token_hash, identifier)
    return StreamingResponse(events(sessions, token_hash, identifier), media_type='text/event-stream', headers={'Cache-Control':'no-store, no-transform', 'X-Accel-Buffering':'no'})


@router.post('/api/v1/jobs/{identifier}/retry')
async def retry(identifier: str, body: RetryJob, actor=AUTH, db=DB):
    item = await owned(db, Job, identifier, actor, lock=True)
    if item.kind == 'document':
        document = await owned(db, Attachment, item.target_id, actor)
        await active_message(db, document.message_id, actor)
    else:
        await active_message(db, item.target_id, actor) if item.kind == 'message' else await owned(db, Report, item.target_id, actor)
    if item.state not in ('failed', 'awaiting_retry'):
        problem(409, '当前任务不需要重试')
    await business_require(db, actor, item.access)
    if item.access and item.access.get('role') != actor.role:
        problem(403, '账号权限已变化，请重新提问')
    item.state, item.error, item.request_started = 'queued', '', False
    if body.useCurrentConfig:
        item.model_binding = None
        item.config_attempt += 1
        if item.kind == 'report':
            item.result = {k: v for k, v in item.result.items() if k != 'reportSaved'}
    item.attempt += 1
    from paa_server.tasks.feedback_state import update_feedback
    update_feedback(item, 'queued', '')
    item.updated_at = now()
    return job_dto(item)
