from datetime import datetime
from paa_server.db.base import Base, Owned, now
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Job(Owned, Base):
    __tablename__ = 'company_job'
    feedback: Mapped[dict] = mapped_column(JSONB, default=dict)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    model_binding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    config_attempt: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(12))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    phase: Mapped[str] = mapped_column(String(30), default='saved')
    error: Mapped[str] = mapped_column(Text, default='')
    fence: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_started: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    base_revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


Index('company_job_one_running_owner', Job.owner_id, unique=True, postgresql_where=Job.state == 'running')
