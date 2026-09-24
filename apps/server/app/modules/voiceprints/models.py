from datetime import datetime
from app.db.base import Base, Record, now
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Voiceprint(Record, Base):
    __tablename__ = 'company_voiceprint'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), unique=True)
    state: Mapped[str] = mapped_column(String(16), default='queued')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    model_id: Mapped[str] = mapped_column(String(120), default='')
    templates: Mapped[list] = mapped_column(JSONB, default=list)
    ready_path: Mapped[str] = mapped_column(String(80), default='')
    pending_path: Mapped[str] = mapped_column(String(80), default='')
    filename: Mapped[str] = mapped_column(String(160), default='')
    error: Mapped[str] = mapped_column(String(220), default='')
    speech_seconds: Mapped[int] = mapped_column(Integer, default=0)
    consent_by: Mapped[str] = mapped_column(ForeignKey('company_member.id'))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
