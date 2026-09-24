from datetime import datetime
from paa_server.db.base import Base, Owned, Record, now
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Report(Owned, Base):
    __tablename__ = 'company_report'
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(10))
    period: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[str] = mapped_column(String(10))
    timezone: Mapped[str] = mapped_column(String(80))
    content: Mapped[dict] = mapped_column(JSONB, default=dict)
    candidate: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_ids: Mapped[list] = mapped_column(JSONB, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_revision: Mapped[int] = mapped_column(Integer, default=0)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('owner_id', 'kind', 'period'),)


class ReportRevision(Owned, Base):
    __tablename__ = 'company_report_revision'
    report_id: Mapped[str] = mapped_column(ForeignKey('company_report.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    source_ids: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('report_id', 'revision'),)


class ReportSchedule(Record, Base):
    __tablename__ = 'company_report_schedule'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(80))
    rule: Mapped[dict] = mapped_column(JSONB)
    effective_period: Mapped[str] = mapped_column(String(10))
    next_period: Mapped[str] = mapped_column(String(10))
    __table_args__ = (UniqueConstraint('company_id', 'kind', 'revision'),)


class ReportEligibility(Owned, Base):
    __tablename__ = 'company_report_eligibility'
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportObligation(Owned, Base):
    __tablename__ = 'company_report_obligation'
    kind: Mapped[str] = mapped_column(String(10))
    period: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[str] = mapped_column(String(10))
    timezone: Mapped[str] = mapped_column(String(80))
    rule_revision: Mapped[int] = mapped_column(Integer)
    generate_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminders: Mapped[bool] = mapped_column(Boolean)
    before_minutes: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default='pending')
    report_id: Mapped[str | None] = mapped_column(ForeignKey('company_report.id'), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generation_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('owner_id', 'kind', 'period'),)


class ReportNotification(Owned, Base):
    __tablename__ = 'company_report_notification'
    obligation_id: Mapped[str] = mapped_column(ForeignKey('company_report_obligation.id'), unique=True)
    stage: Mapped[str] = mapped_column(String(16))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
