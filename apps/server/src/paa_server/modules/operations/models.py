from datetime import datetime
from paa_server.db.base import Base, Owned, now
from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class BusinessAction(Owned, Base):
    """Durable business receipts survive message/checkpoint removal."""
    __tablename__ = 'company_business_action'
    message_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    step: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    digest: Mapped[str] = mapped_column(String(64))
    intent_key: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(24), default='pending')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('message_id', 'step'), UniqueConstraint('message_id', 'intent_key'))
