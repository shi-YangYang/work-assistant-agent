from datetime import datetime
from app.db.base import Base, Owned, now
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class WorkItem(Owned, Base):
    __tablename__ = 'company_work_item'
    origin: Mapped[str] = mapped_column(String(16), default='suggestion')
    business_links: Mapped[list] = mapped_column(JSONB, default=list)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkRevision(Owned, Base):
    __tablename__ = 'company_work_revision'
    origin: Mapped[str] = mapped_column(String(24), default='unknown', server_default='unknown')
    business_links: Mapped[list] = mapped_column(JSONB, default=list)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    work_id: Mapped[str] = mapped_column(ForeignKey('company_work_item.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    source_ids: Mapped[list] = mapped_column(JSONB)
    publication: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    __table_args__ = (UniqueConstraint('work_id', 'revision'),)


class ProgressDraft(Owned, Base):
    __tablename__ = 'company_progress_draft'
    business_links: Mapped[list] = mapped_column(JSONB, default=list)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    message_id: Mapped[str] = mapped_column(ForeignKey('company_message.id'), index=True)
    work_id: Mapped[str | None] = mapped_column(ForeignKey('company_work_item.id'), nullable=True)
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    tool_key: Mapped[str] = mapped_column(String(200), unique=True)


class WorkUpdate(Owned, Base):
    __tablename__ = 'company_work_update'
    work_id: Mapped[str] = mapped_column(ForeignKey('company_work_item.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(String(12000), default='')
    material_ids: Mapped[list] = mapped_column(JSONB, default=list)
    origin: Mapped[str] = mapped_column(String(24), default='manual')
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    work_revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkUpdateRevision(Owned, Base):
    __tablename__ = 'company_work_update_revision'
    update_id: Mapped[str] = mapped_column(ForeignKey('company_work_update.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(12000), default='')
    material_ids: Mapped[list] = mapped_column(JSONB, default=list)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    work_revision: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(24))
    __table_args__ = (UniqueConstraint('update_id', 'revision'),)


class WorkMaterial(Owned, Base):
    __tablename__ = 'company_work_material'
    work_id: Mapped[str] = mapped_column(ForeignKey('company_work_item.id'), index=True)
    attachment_id: Mapped[str] = mapped_column(ForeignKey('company_attachment.id'), index=True)
    source: Mapped[dict] = mapped_column(JSONB, default=dict)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
