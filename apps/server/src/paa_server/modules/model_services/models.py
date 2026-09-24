from datetime import datetime
from paa_server.db.base import Base, Owned, Record, now
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ModelUsage(Owned, Base):
    __tablename__ = 'company_model_usage'
    status: Mapped[str] = mapped_column(String(16), default='legacy')
    service_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_fence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey('company_job.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class ModelService(Record, Base):
    __tablename__ = 'company_model_service'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(2048))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    models: Mapped[list] = mapped_column(JSONB, default=list)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelServiceRevision(Record, Base):
    __tablename__ = 'company_model_service_revision'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey('company_model_service.id'))
    revision: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(2048))
    models: Mapped[list] = mapped_column(JSONB)
    credential: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('service_id', 'revision'),)


class ModelRouting(Base):
    __tablename__ = 'company_model_routing'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    choices: Mapped[dict] = mapped_column(JSONB)


class ModelCheck(Record, Base):
    __tablename__ = 'company_model_check'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
