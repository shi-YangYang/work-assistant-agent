from datetime import timedelta
from fastapi import APIRouter, HTTPException, Header, Query
from math import ceil
from paa_server.core.versions import version
from paa_server.db.base import now
from paa_server.db.idempotency import idem_begin, idem_save
from paa_server.http.dependencies import ADMIN, AUTH, DB
from paa_server.modules.support.models import SupportFeedback
from paa_server.modules.support.schemas import FeedbackCreate, FeedbackPatch
from paa_server.modules.support.service import dto, record, visible
from sqlalchemy import select
from typing import Annotated, Literal

router = APIRouter()


@router.post('/api/v1/support-feedback', status_code=201)
async def create_feedback(body: FeedbackCreate, idempotency_key: Annotated[str | None, Header(max_length=100)] = None, actor=AUTH, db=DB):
    payload = body.model_dump(mode='json', exclude_none=True)
    prior, digest = await idem_begin(db, actor, 'support-feedback', idempotency_key, payload)
    if prior:
        return prior
    # idem_begin serializes this identity, so concurrent submissions cannot
    # bypass the rolling quota. Replays above never consume another slot.
    instant = now()
    recent = list((await db.scalars(select(SupportFeedback.created_at).where(
        SupportFeedback.company_id == actor.company_id,
        SupportFeedback.owner_id == actor.id,
        SupportFeedback.created_at > instant - timedelta(minutes=10),
    ).order_by(SupportFeedback.created_at.desc()).limit(5))).all())
    if len(recent) == 5:
        wait = max(1, ceil((recent[-1] + timedelta(minutes=10) - instant).total_seconds()))
        raise HTTPException(status_code=429, detail={
            'code': 'feedback_rate_limited', 'message': '反馈提交较频繁，请稍后再试',
            'retryAfter': wait,
        }, headers={'Retry-After': str(wait)})
    item = SupportFeedback(company_id=actor.company_id, owner_id=actor.id,
                           description=body.description, diagnostics=payload['diagnostics'])
    db.add(item)
    await db.flush()
    return idem_save(db, actor, 'support-feedback', idempotency_key, digest, dto(item, actor.name))


@router.get('/api/v1/support-feedback')
async def list_feedback(state: Literal['pending', 'resolved'] | None = None, scope: Literal['all', 'mine'] = 'all', cursor: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=20), actor=AUTH, db=DB):
    query = visible(actor)
    if scope == 'mine':
        query = query.where(SupportFeedback.owner_id == actor.id)
    if state is not None:
        query = query.where(SupportFeedback.state == state)
    rows = (await db.execute(query.order_by(SupportFeedback.created_at.desc(), SupportFeedback.id.desc()).offset(cursor).limit(limit + 1))).all()
    return {'items': [dto(item, name) for item, name in rows[:limit]],
            'nextCursor': str(cursor + limit) if len(rows) > limit else None}


@router.get('/api/v1/support-feedback/{identifier}')
async def get_feedback(identifier: str, actor=AUTH, db=DB):
    return dto(*await record(db, actor, identifier))


@router.patch('/api/v1/support-feedback/{identifier}')
async def update_feedback(identifier: str, body: FeedbackPatch, actor=ADMIN, db=DB):
    item, name = await record(db, actor, identifier, lock=True)
    version(item, body.expectedRevision)
    item.state, item.handling_note = body.state, body.handlingNote.strip()
    item.revision += 1
    item.updated_at = now()
    return dto(item, name)
