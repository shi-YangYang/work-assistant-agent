"""User-submitted support records, separate from agent task feedback and context."""
from datetime import timedelta
from math import ceil
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Header, HTTPException, Query
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from .models import Member, SupportFeedback, now
from .schemas import Input
from .service import idem_begin, idem_save, problem, version


class SupportDiagnostics(Input):
    occurredAt: AwareDatetime | None = None
    page: Literal[
        '/', '/login', '/assistant', '/assistant/:conversationId', '/messages/:id',
        '/work', '/work/:id', '/reports', '/reports/:id', '/team', '/team/details',
        '/team/reports', '/team/:id', '/members', '/settings/account',
        '/settings/appearance', '/settings/rules', '/settings/models',
        '/settings/usage', '/settings/support',
    ] | None = None
    category: Literal[
        'network', 'timeout', 'unauthorized', 'forbidden', 'rate_limited', 'server',
        'invalid_response', 'conflict', 'validation', 'cancelled', 'unknown',
    ] | None = None
    httpStatus: int | None = Field(default=None, ge=100, le=599, strict=True)
    requestId: UUID | None = None
    appVersion: str | None = Field(default=None, max_length=80, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._+\-]{0,79}$')
    browser: str | None = Field(default=None, max_length=80, pattern=r'^(Chrome|Safari|Firefox|Edge|Opera|Samsung Internet|WeChat|DingTalk|Unknown)( [0-9][0-9.]*)?$')
    os: str | None = Field(default=None, max_length=80, pattern=r'^(Windows|macOS|iOS|iPadOS|Android|Linux|Unknown)( [0-9][0-9._]*)?$')
    viewport: str | None = Field(default=None, max_length=11, pattern=r'^[1-9][0-9]{0,4}x[1-9][0-9]{0,4}$')


class FeedbackCreate(Input):
    description: str = Field(min_length=1, max_length=4000)
    diagnostics: SupportDiagnostics = Field(default_factory=SupportDiagnostics)

    @model_validator(mode='after')
    def nonempty(self):
        self.description = self.description.strip()
        if not self.description:
            raise ValueError('请填写问题描述')
        return self


class FeedbackPatch(Input):
    state: Literal['pending', 'resolved']
    handlingNote: str = Field(max_length=2000)
    expectedRevision: int = Field(ge=1, strict=True)


def dto(item, owner_name):
    return {
        'id': item.id, 'ownerId': item.owner_id, 'ownerName': owner_name,
        'description': item.description, 'diagnostics': item.diagnostics,
        'state': item.state, 'handlingNote': item.handling_note,
        'revision': item.revision, 'createdAt': item.created_at.isoformat(),
        'updatedAt': item.updated_at.isoformat(),
    }


def visible(actor):
    query = select(SupportFeedback, Member.name).join(
        Member, (Member.id == SupportFeedback.owner_id) & (Member.company_id == actor.company_id),
    ).where(SupportFeedback.company_id == actor.company_id)
    if actor.role != 'admin':
        query = query.where(SupportFeedback.owner_id == actor.id)
    return query


async def record(db, actor, identifier, *, lock=False):
    query = visible(actor).where(SupportFeedback.id == identifier)
    if lock:
        query = query.with_for_update(of=SupportFeedback)
    row = (await db.execute(query)).first()
    if row is None:
        problem(404, '反馈不存在或无权查看')
    return row


def register_routes(app, AUTH, ADMIN, DB):
    @app.post('/api/v1/support-feedback', status_code=201)
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

    @app.get('/api/v1/support-feedback')
    async def list_feedback(state: Literal['pending', 'resolved'] | None = None, scope: Literal['all', 'mine'] = 'all', cursor: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=20), actor=AUTH, db=DB):
        query = visible(actor)
        if scope == 'mine':
            query = query.where(SupportFeedback.owner_id == actor.id)
        if state is not None:
            query = query.where(SupportFeedback.state == state)
        rows = (await db.execute(query.order_by(SupportFeedback.created_at.desc(), SupportFeedback.id.desc()).offset(cursor).limit(limit + 1))).all()
        return {'items': [dto(item, name) for item, name in rows[:limit]],
                'nextCursor': str(cursor + limit) if len(rows) > limit else None}

    @app.get('/api/v1/support-feedback/{identifier}')
    async def get_feedback(identifier: str, actor=AUTH, db=DB):
        return dto(*await record(db, actor, identifier))

    @app.patch('/api/v1/support-feedback/{identifier}')
    async def update_feedback(identifier: str, body: FeedbackPatch, actor=ADMIN, db=DB):
        item, name = await record(db, actor, identifier, lock=True)
        version(item, body.expectedRevision)
        item.state, item.handling_note = body.state, body.handlingNote.strip()
        item.revision += 1
        item.updated_at = now()
        return dto(item, name)
