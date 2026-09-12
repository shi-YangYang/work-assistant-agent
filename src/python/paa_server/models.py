from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Company(Record, Base):
    __tablename__ = 'company'
    name: Mapped[str] = mapped_column(String(120))
    rules: Mapped[dict] = mapped_column(JSONB, default=lambda: {'timezone': 'Asia/Shanghai', 'daily': {'enabled': False, 'days': [0, 1, 2, 3, 4, 5, 6], 'generateTime': '', 'deadline': ''}, 'weekly': {'enabled': False, 'days': [4], 'generateTime': '', 'deadline': ''}})
    revision: Mapped[int] = mapped_column(Integer, default=1)
    rules_effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Member(Record, Base):
    __tablename__ = 'company_member'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(12), default='employee')
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)


class Session(Record, Base):
    __tablename__ = 'company_session'
    member_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Record, Base):
    __tablename__ = 'company_login_attempt'
    identity: Mapped[str] = mapped_column(String(64), index=True)


class Owned(Record):
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)


class Message(Owned, Base):
    __tablename__ = 'company_message'
    text: Mapped[str] = mapped_column(Text, default='')
    reply: Mapped[str] = mapped_column(Text, default='')
    suggestions: Mapped[list] = mapped_column(JSONB, default=list)
    transcript: Mapped[str] = mapped_column(Text, default='')
    transcript_revision: Mapped[int] = mapped_column(Integer, default=0)
    transcript_history: Mapped[list] = mapped_column(JSONB, default=list)
    reply_to: Mapped[str | None] = mapped_column(ForeignKey('company_message.id'), nullable=True)


class Attachment(Owned, Base):
    __tablename__ = 'company_attachment'
    message_id: Mapped[str | None] = mapped_column(ForeignKey('company_message.id'), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))
    mime: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(180))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    duration: Mapped[float | None] = mapped_column(nullable=True)


class WorkItem(Owned, Base):
    __tablename__ = 'company_work_item'
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkRevision(Owned, Base):
    __tablename__ = 'company_work_revision'
    work_id: Mapped[str] = mapped_column(ForeignKey('company_work_item.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    source_ids: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('work_id', 'revision'),)


class ProgressDraft(Owned, Base):
    __tablename__ = 'company_progress_draft'
    message_id: Mapped[str] = mapped_column(ForeignKey('company_message.id'), index=True)
    work_id: Mapped[str | None] = mapped_column(ForeignKey('company_work_item.id'), nullable=True)
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    tool_key: Mapped[str] = mapped_column(String(200), unique=True)


class Report(Owned, Base):
    __tablename__ = 'company_report'
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


class Job(Owned, Base):
    __tablename__ = 'company_job'
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


class Idempotency(Owned, Base):
    __tablename__ = 'company_idempotency'
    action: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('owner_id', 'action', 'key'),)


class ModelUsage(Owned, Base):
    __tablename__ = 'company_model_usage'
    job_id: Mapped[str] = mapped_column(ForeignKey('company_job.id'))
    kind: Mapped[str] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
