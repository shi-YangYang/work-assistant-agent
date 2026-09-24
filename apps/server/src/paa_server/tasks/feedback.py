import asyncio
import json
import re
import time
from .feedback_state import update_feedback
from datetime import timedelta
from fastapi import HTTPException
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.modules.auth.models import Session
from paa_server.modules.conversations.models import Conversation
from paa_server.modules.members.models import Member
from paa_server.modules.messages.models import Message
from paa_server.security.access import require as business_require
from paa_server.security.locks import company_lock as business_company_lock
from paa_server.tasks.models import Job
from sqlalchemy import select

TERMINAL = frozenset({'succeeded', 'awaiting_input', 'failed', 'awaiting_retry', 'cancelled'})


async def publish(context, stage, text='', call_id=None, *, force=False):
    from paa_server.tasks.lease import lease
    instant = time.monotonic()
    if not force and instant - context.feedback_at < 0.2:
        return
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'message':
            return
        # Inherited or freshly queried team evidence stays behind the complete
        # citation boundary, regardless of which role submitted the message.
        if job.access.get('team'):
            text = ''
        update_feedback(job, stage, text, call_id)
    context.feedback_at = instant


def presentation_text(text):
    # Citation markers and internal identifiers are delivered only by the final
    # validated message DTO. Do not expose a half-written marker or tool payload.
    if not isinstance(text, str):
        return ''
    marker = re.search(r'\[|<|\{|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b|(?:find_|get_|propose_|draft_|query_|read_|execute_)[a-z_]+', text, re.I)
    return text[:marker.start() if marker else 16000]


async def snapshot(sessions, token_hash, job_id):
    # Short transactions only: no connection/row/advisory lock across SSE yield.
    async with sessions.begin() as db:
        session = await db.scalar(select(Session).where(Session.token_hash == token_hash, Session.expires_at > now()))
        actor = await db.get(Member, session.member_id) if session else None
        if not actor or not actor.active:
            problem(401, '登录已过期，请重新登录', 'login_required')
        await business_company_lock(db, actor.company_id)
        await db.refresh(actor)
        session = await db.scalar(select(Session).where(Session.token_hash == token_hash, Session.member_id == actor.id, Session.expires_at > now()))
        if not actor.active or not session:
            problem(401, '登录已过期，请重新登录', 'login_required')
        job = await db.scalar(select(Job).where(Job.id == job_id, Job.company_id == actor.company_id, Job.owner_id == actor.id, Job.kind == 'message'))
        message = await db.get(Message, job.target_id) if job else None
        if not message or message.deleted:
            problem(404, '消息不存在或无权查看')
        conversation = await db.get(Conversation, message.conversation_id) if message.conversation_id else None
        if conversation and (conversation.deleted or conversation.owner_id != actor.id or conversation.company_id != actor.company_id):
            problem(404, '会话不存在或无权查看')
        await business_require(db, actor, job.access)
        await business_require(db, actor, message.access)
        if job.access and job.access.get('role') != actor.role:
            problem(403, '账号权限已变化，请重新提问', 'business_access_changed')
        feedback = job.feedback or {}
        text = feedback.get('text','') if not job.access.get('team') and job.state not in ('succeeded','awaiting_input','cancelled') and job.updated_at >= now() - timedelta(days=1) else ''
        from paa_server.modules.operations.receipts import message_actions
        actions = await message_actions(db, actor, message)
        return {'jobId':job.id,'attempt':job.attempt,'fence':job.fence,'seq':feedback.get('seq',0), 'state':job.state,'stage':'queued' if job.state == 'queued' else feedback.get('stage','generating'), 'text':text,'error':job.error,'updatedAt':job.updated_at.isoformat(), 'actions':actions}


async def events(sessions, token_hash, job_id):
    previous = None
    for index in range(120):  # Browser reconnects read-only; no indefinitely held request.
        try:
            value = await snapshot(sessions, token_hash, job_id)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail,dict) else {'message':'订阅已结束'}
            yield 'event: unavailable\ndata: ' + json.dumps({'status':error.status_code, **detail},ensure_ascii=False) + '\n\n'
            return
        # A target can become unavailable or a report can finish independently
        # of the assistant's next phase. Do not keep a stale card on screen.
        stamp = (value['attempt'],value['fence'],value['seq'],value['state'],value['updatedAt'],json.dumps(value['actions'], sort_keys=True))
        if stamp != previous:
            yield 'event: snapshot\nid: ' + ':'.join(map(str, stamp[:3])) + '\ndata: ' + json.dumps(value,ensure_ascii=False) + '\n\n'
            previous = stamp
        elif index % 10 == 0:
            yield ': heartbeat\n\n'
        if value['state'] in TERMINAL:
            return
        await asyncio.sleep(0.5)
