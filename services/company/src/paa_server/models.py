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
    environment_models: Mapped[bool] = mapped_column(Boolean, default=False)
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


class Conversation(Owned, Base):
    __tablename__ = 'company_conversation'
    title: Mapped[str] = mapped_column(String(120), default='新会话')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Owned, Base):
    __tablename__ = 'company_message'
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey('company_conversation.id'), nullable=True, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text, default='')
    reply: Mapped[str] = mapped_column(Text, default='')
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    suggestions: Mapped[list] = mapped_column(JSONB, default=list)
    transcript: Mapped[str] = mapped_column(Text, default='')
    transcript_revision: Mapped[int] = mapped_column(Integer, default=0)
    transcript_history: Mapped[list] = mapped_column(JSONB, default=list)
    reply_to: Mapped[str | None] = mapped_column(ForeignKey('company_message.id'), nullable=True)


class Attachment(Owned, Base):
    __tablename__ = 'company_attachment'
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    message_id: Mapped[str | None] = mapped_column(ForeignKey('company_message.id'), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))
    mime: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(180))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    duration: Mapped[float | None] = mapped_column(nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(16), default='none')
    extraction_revision: Mapped[int] = mapped_column(Integer, default=0)
    parser_version: Mapped[str] = mapped_column(String(80), default='')
    extraction_info: Mapped[dict] = mapped_column(JSONB, default=dict)


class DocumentChunk(Owned, Base):
    __tablename__ = 'company_document_chunk'
    attachment_id: Mapped[str] = mapped_column(ForeignKey('company_attachment.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('attachment_id', 'revision', 'ordinal'),)


class WorkItem(Owned, Base):
    __tablename__ = 'company_work_item'
    business_links: Mapped[list] = mapped_column(JSONB, default=list)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkRevision(Owned, Base):
    __tablename__ = 'company_work_revision'
    business_links: Mapped[list] = mapped_column(JSONB, default=list)
    access: Mapped[dict] = mapped_column(JSONB, default=dict)
    work_id: Mapped[str] = mapped_column(ForeignKey('company_work_item.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    source_ids: Mapped[list] = mapped_column(JSONB)
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


class Idempotency(Owned, Base):
    __tablename__ = 'company_idempotency'
    action: Mapped[str] = mapped_column(String(160))
    key: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('owner_id', 'action', 'key'),)


class SupportFeedback(Owned, Base):
    __tablename__ = 'company_support_feedback'
    description: Mapped[str] = mapped_column(Text)
    diagnostics: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(16), default='pending')
    handling_note: Mapped[str] = mapped_column(Text, default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index('ix_support_feedback_company_state_created', 'company_id', 'state', 'created_at'),
        Index('ix_support_feedback_owner_created', 'owner_id', 'created_at'),
    )


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
