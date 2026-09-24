from datetime import datetime
from paa_server.db.base import Base, Record
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class Session(Record, Base):
    __tablename__ = 'company_session'
    member_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Record, Base):
    __tablename__ = 'company_login_attempt'
    identity: Mapped[str] = mapped_column(String(64), index=True)


class DingTalkConfig(Record, Base):
    __tablename__ = 'company_dingtalk_config'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), unique=True)
    corp_id: Mapped[str] = mapped_column(String(128))
    client_id: Mapped[str] = mapped_column(String(128))
    credential: Mapped[str] = mapped_column(Text, default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DingTalkIdentity(Record, Base):
    __tablename__ = 'company_dingtalk_identity'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), unique=True)
    corp_id: Mapped[str] = mapped_column(String(128))
    client_id: Mapped[str] = mapped_column(String(128))
    union_id: Mapped[str] = mapped_column(String(256))
    user_id: Mapped[str] = mapped_column(String(256))
    __table_args__ = (
        UniqueConstraint('company_id', 'corp_id', 'client_id', 'union_id'),
        UniqueConstraint('company_id', 'corp_id', 'client_id', 'user_id'),
    )


class DingTalkAuthorization(Record, Base):
    __tablename__ = 'company_dingtalk_authorization'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    config_revision: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16))
    member_id: Mapped[str | None] = mapped_column(ForeignKey('company_member.id'), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    proof_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proof_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesktopAuthorization(Record, Base):
    __tablename__ = 'company_desktop_authorization'
    request_hash: Mapped[str] = mapped_column(String(64), unique=True)
    challenge: Mapped[str] = mapped_column(String(43))
    state: Mapped[str] = mapped_column(String(16), default='pending')
    company_id: Mapped[str | None] = mapped_column(ForeignKey('company.id'), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ForeignKey('company_member.id'), nullable=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey('company_session.id', ondelete='CASCADE'), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesktopSession(Record, Base):
    __tablename__ = 'company_desktop_session'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('company_session.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
