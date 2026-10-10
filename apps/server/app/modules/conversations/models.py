from datetime import datetime
from app.core.personas import DEFAULT_PERSONA, LEGACY_PERSONA
from app.db.base import Base, Owned, now
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


class Conversation(Owned, Base):
    __tablename__ = 'company_conversation'
    persona_id: Mapped[str] = mapped_column(String(32), default=DEFAULT_PERSONA, server_default=LEGACY_PERSONA)
    title: Mapped[str] = mapped_column(String(120), default='新会话')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConversationContext(Base):
    """Rebuildable reference data, kept off the conversation list's hot row."""
    __tablename__ = 'company_conversation_context'
    from sqlalchemy import ForeignKey
    from sqlalchemy.dialects.postgresql import JSONB
    conversation_id: Mapped[str] = mapped_column(ForeignKey('company_conversation.id', ondelete='CASCADE'), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    invalidation_version: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConversationTaskState(Base):
    """Durable task intent; independent from the rebuildable context cache."""
    __tablename__ = 'company_conversation_task_state'
    from sqlalchemy import ForeignKey
    from sqlalchemy.dialects.postgresql import JSONB
    conversation_id: Mapped[str] = mapped_column(ForeignKey('company_conversation.id', ondelete='CASCADE'), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
