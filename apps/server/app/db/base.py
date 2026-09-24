from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid import uuid4


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Owned(Record):
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('company_member.id'), index=True)
