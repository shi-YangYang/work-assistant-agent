from app.db.base import Base, Owned, now
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Deliverable(Owned, Base):
    __tablename__ = 'company_deliverable'
    conversation_id: Mapped[str] = mapped_column(ForeignKey('company_conversation.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DeliverableRevision(Owned, Base):
    __tablename__ = 'company_deliverable_revision'
    deliverable_id: Mapped[str] = mapped_column(ForeignKey('company_deliverable.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str] = mapped_column(ForeignKey('company_message.id'), index=True)
    step: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JSONB, default=list)
    digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('deliverable_id', 'revision'), UniqueConstraint('message_id', 'step'))


class DeliverableLink(Owned, Base):
    __tablename__ = 'company_deliverable_link'
    deliverable_id: Mapped[str] = mapped_column(ForeignKey('company_deliverable.id'), index=True)
    item_id: Mapped[str] = mapped_column(String(36))
    work_id: Mapped[str] = mapped_column(ForeignKey('company_work_item.id'), index=True)
    source_revision: Mapped[int] = mapped_column(Integer)
    action_id: Mapped[str] = mapped_column(ForeignKey('company_business_action.id'), unique=True)
