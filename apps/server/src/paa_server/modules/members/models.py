from datetime import datetime
from paa_server.db.base import Base, Record, now
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


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
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    __table_args__ = (CheckConstraint('NOT deleted OR NOT active', name='ck_company_member_deleted_inactive'),)
