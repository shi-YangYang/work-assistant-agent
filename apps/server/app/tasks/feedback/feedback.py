import asyncio
import json
import re
import time
from itertools import count
from .feedback_state import update_feedback
from .image_feedback import dto as image_dto
from datetime import timedelta
from fastapi import HTTPException
from app.core.errors import problem
from app.db.base import now
from app.modules.auth.models import Session
from app.modules.auth.sessions import live_session
from app.modules.conversations.models import Conversation
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.security.access import require as business_require
from app.security.locks import company_lock as business_company_lock
from app.tasks.models import Job
from sqlalchemy import select

TERMINAL = frozenset({'succeeded', 'awaiting_input', 'failed', 'awaiting_retry', 'cancelled'})


async def publish(context, stage, text='', call_id=None, *, force=False):
    from app.tasks.lease import lease
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


async def snapshot(sessions, token_hash, job_id, *, transport=False, temporary=None):
    # Short transactions only: no connection/row/advisory lock across SSE yield.
    async with sessions.begin() as db:
        session = await db.scalar(select(Session).where(Session.token_hash == token_hash, *live_session(now())))
        actor = await db.get(Member, session.member_id) if session else None
        if not actor or not actor.active:
            problem(401, '登录已过期，请重新登录', 'login_required')
        await business_company_lock(db, actor.company_id)
        await db.refresh(actor)
        session = await db.scalar(select(Session).where(Session.token_hash == token_hash, Session.member_id == actor.id, *live_session(now())))
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
        from app.tasks.nodes.node_state import node_dtos
        from app.modules.operations.receipts import message_actions
        actions = await message_actions(db, actor, message)
        from app.tasks.feedback.context_feedback import usage_dto
        from app.tasks.feedback.outcomes import refresh, dto as outcome_dto
        from app.modules.work.drafts.draft_receipts import message_drafts
        drafts = await message_drafts(db, actor, message, job)
        refresh(job, actions, drafts)
        from app.modules.interactions.serializers import message_interactions
        interactions = await message_interactions(db, actor, message)
        from app.tasks.feedback.reply_stream import dto as reply_dto
        reply_stream = await reply_dto(db, actor, job, message)
        transport_metadata = {}
        if transport:
            transport_metadata = {'_reply': {'company': job.company_id, 'owner': job.owner_id,
                                           'call': feedback.get('replyStreamCall'),
                                           'control': feedback.get('replyStream', {})}}
        if temporary is not None and job.state not in TERMINAL:
            from app.tasks.feedback.reply_stream import validate_sources, presentation_text as reply_text
            from app.integrations.models.transport import ProviderError
            allowed = (job.state == 'running' and not temporary.get('sealed') and
                       temporary.get('attempt') == job.attempt and temporary.get('fence') == job.fence and
                       temporary.get('callId') == feedback.get('replyStreamCall') and
                       temporary.get('generation') == feedback.get('replyStream', {}).get('generation') and
                       not job.access.get('team') and not message.access.get('team'))
            try:
                if allowed and await validate_sources(db, actor, job, message, temporary.get('source', {})):
                    allowed = False
            except (ValueError, HTTPException, ProviderError):
                allowed = False
            reply_stream = {'version': 1, 'generation': temporary.get('generation', 0),
                            'state': temporary.get('state', 'streaming') if allowed else 'withdrawn',
                            'text': reply_text(temporary.get('text', '')) if allowed else ''}

        return {**transport_metadata, 'imageGeneration': image_dto(job), 'imageDeliveryCount': job.result.get('imageDeliveryCount', 0), 'replyStream': reply_stream, 'interactions': interactions, 'taskOutcome': outcome_dto(job), 'contextUsage': usage_dto(job), 'incompleteTask': bool(job.result.get('incompleteTask')), 'nodes':node_dtos(job),'jobId':job.id,'attempt':job.attempt,'fence':job.fence,'seq':feedback.get('seq',0), 'state':job.state,'stage':'queued' if job.state == 'queued' else feedback.get('stage','generating'), 'text':text,'error':job.error,'updatedAt':job.updated_at.isoformat(), 'actions':actions}


def event(name, value):
    return 'event: ' + name + '\ndata: ' + json.dumps(value, ensure_ascii=False) + '\n\n'


async def events(sessions, token_hash, job_id, *, settings=None, version=1):
    if settings is None:
        # Existing callers/tests that only exercise durable state.
        async for value in legacy_events(sessions, token_hash, job_id):
            yield value
        return
    from app.tasks.streaming.protocol import Identity
    from app.tasks.streaming.redis_store import store_for, StreamUnavailable
    store = store_for(settings)
    from app.tasks.timing import Timing
    timing = None
    def emit(name, value):
        if timing and name.startswith('reply_'):
            timing.mark('sse.send', generation=value.get('generation'), seq=value.get('seq'), bytes=len(value.get('text', value.get('delta', '')).encode()))
        return event(name, value)
    previous, identity, cursor, generation, seq = None, None, '0-0', None, 0
    cached_reply = cached_data = None
    def withdraw(value, public):
        nonlocal cached_reply, previous
        cached_reply = {'version': 1, 'generation': public['generation'], 'state': 'withdrawn', 'text': ''}
        if version == 1:
            value = {**value, 'replyStream': cached_reply}
            previous = json.dumps(value, sort_keys=True)
            return emit('snapshot', value)
        return emit('reply_withdrawn', {**public, 'state': 'withdrawn'})
    disabled = False
    next_state = 0
    heartbeat_at = time.monotonic()
    while True:
        instant = time.monotonic()
        if instant - heartbeat_at >= 10:
            yield ': heartbeat\n\n'
            heartbeat_at = instant
        if instant >= next_state:
            try:
                value = await snapshot(sessions, token_hash, job_id, transport=True)
            except HTTPException as error:
                yield emit('unavailable', {'status': error.status_code})
                return
            metadata = value.pop('_reply')
            current = Identity(metadata['company'], metadata['owner'], job_id, value['attempt'], value['fence'])
            if current != identity:
                identity, cursor, generation, seq, cached_reply = current, '0-0', None, 0, None
                cached_data, disabled = None, False
                timing = Timing(job_id, current.attempt, current.fence)
            if value['state'] in TERMINAL:
                yield emit('snapshot', value)
                return
            control = metadata['control']
            if cached_data and cached_data.get('generation') != control.get('generation'):
                cached_data = None
                yield withdraw(value, {**identity.public(), 'generation': control.get('generation', 0), 'seq': 0})
            elif cached_data:
                try:
                    checked = await snapshot(sessions, token_hash, job_id, temporary=cached_data)
                except HTTPException as error:
                    yield emit('unavailable', {'status': error.status_code})
                    return
                if checked['replyStream']['state'] == 'withdrawn':
                    try:
                        await store.seal(identity, closed=False, generation=cached_data['generation'])
                    except StreamUnavailable:
                        pass
                    cached_data = None
                    yield withdraw(checked, {**identity.public(), 'generation': generation, 'seq': seq + 1})
            if control.get('state') == 'unavailable' and not disabled:
                disabled = True
                yield emit('reply_unavailable', {**identity.public(), 'generation': control.get('generation', 0), 'seq': seq + 1,
                                                  'message': '实时预览暂不可用，任务仍在后台处理。'})
            if version == 1 and cached_reply:
                value['replyStream'] = cached_reply
            stamp = json.dumps(value, sort_keys=True)
            if stamp != previous:
                yield emit('snapshot', value)
                previous = stamp
            next_state = time.monotonic() + .5
        if disabled:
            await asyncio.sleep(max(0, next_state - time.monotonic()))
            continue
        try:
            rows = [] if cursor == '0-0' else await store.read(identity, cursor)
            current = await store.snapshot(identity)
            if not current and generation is not None:
                raise StreamUnavailable('reply_stream_lost')
            if current and current.get('sealed'):
                finished = await snapshot(sessions, token_hash, job_id)
                if finished['state'] in TERMINAL:
                    yield emit('snapshot', finished)
                    return
            if not current or current.get('sealed'):
                if generation is not None and cached_reply and cached_reply.get('text'):
                    cached_data = None
                    yield withdraw(finished, {**identity.public(), 'generation': generation, 'seq': seq + 1})
                await asyncio.sleep(min(.05, max(0, next_state - time.monotonic())))
                continue
            if current['generation'] == generation and current['seq'] <= seq:
                continue
            # Permission/source validation is independent of the publisher and
            # repeated before each exposed batch, with no transaction across yield.
            authorized = await snapshot(sessions, token_hash, job_id, temporary=current)
            if authorized['state'] in TERMINAL:
                yield emit('snapshot', authorized)
                return
            reply = authorized['replyStream']
            public = {key: current[key] for key in ('jobId', 'attempt', 'fence', 'generation', 'seq', 'callId', 'state')}
            if reply['state'] == 'withdrawn':
                await store.seal(identity, closed=False, generation=current['generation'])
                yield withdraw(authorized, public)
            elif version == 1:
                authorized['replyStream'] = reply
                yield emit('snapshot', authorized)
                cached_reply = reply
            else:
                contiguous = bool(rows) and current['generation'] == generation
                expected = seq + 1
                for _, row in rows:
                    if row.get('generation') != generation or row.get('seq') != expected or row.get('type') != 'delta':
                        contiguous = False
                        break
                    expected += 1
                contiguous = contiguous and expected - 1 == current['seq']
                if contiguous:
                    for _, row in rows:
                        yield emit('reply_delta', row)
                else:
                    yield emit('reply_sync', {**public, 'text': reply['text'], 'state': reply['state']})
                cached_reply = reply
            generation, seq, cursor = current['generation'], current['seq'], current['cursor']
            cached_data = None if reply['state'] == 'withdrawn' else current
        except HTTPException as error:
            yield emit('unavailable', {'status': error.status_code})
            return
        except StreamUnavailable:
            disabled = True
            yield emit('reply_unavailable', {**identity.public(), 'generation': generation or 0, 'seq': seq + 1,
                                              'message': '实时预览暂不可用，任务仍在后台处理。'})


async def legacy_events(sessions, token_hash, job_id):
    previous = None
    for index in count():
        try:
            value = await snapshot(sessions, token_hash, job_id)
        except HTTPException as error:
            yield event('unavailable', {'status': error.status_code})
            return
        stamp = json.dumps(value, sort_keys=True)
        if stamp != previous:
            yield event('snapshot', value)
            previous = stamp
        elif index % 10 == 0:
            yield ': heartbeat\n\n'
        if value['state'] in TERMINAL:
            return
        await asyncio.sleep(.5)
