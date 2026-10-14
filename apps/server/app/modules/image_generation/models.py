from app.db.base import Base, Owned, now
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ImageGeneration(Owned, Base):
    __tablename__ = 'company_image_generation'
    job_id: Mapped[str] = mapped_column(ForeignKey('company_job.id'), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('company_conversation.id'), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey('company_message.id'), index=True)
    operation: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    fence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default='submitting')
    task_id: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(200))
    provider_result: Mapped[dict] = mapped_column(JSONB, default=dict)
    usage_id: Mapped[str | None] = mapped_column(ForeignKey('company_model_usage.id'))
    binding: Mapped[dict] = mapped_column(JSONB)
    request: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    files: Mapped[list] = mapped_column(JSONB, default=list)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('message_id', 'operation'), UniqueConstraint('message_id', 'fingerprint'))
