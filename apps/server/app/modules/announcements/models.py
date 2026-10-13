from datetime import datetime
from app.db.base import Base, Record, now
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class Announcement(Record, Base):
    __tablename__ = 'company_announcement'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'))
    title: Mapped[str] = mapped_column(String(100))
    markdown: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default='published')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    author_id: Mapped[str | None] = mapped_column(ForeignKey('company_member.id', ondelete='SET NULL'))
    author_name: Mapped[str] = mapped_column(String(200))
    editor_id: Mapped[str | None] = mapped_column(ForeignKey('company_member.id', ondelete='SET NULL'))
    editor_name: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("state IN ('published', 'withdrawn')", name='ck_announcement_state'),
        CheckConstraint('revision >= 1', name='ck_announcement_revision'),
        Index('ix_announcement_company_state_created', 'company_id', 'state', 'created_at', 'id'),
    )


class AnnouncementRead(Record, Base):
    __tablename__ = 'company_announcement_read'
    company_id: Mapped[str] = mapped_column(ForeignKey('company.id'))
    announcement_id: Mapped[str] = mapped_column(ForeignKey('company_announcement.id', ondelete='CASCADE'))
    reader_id: Mapped[str] = mapped_column(ForeignKey('company_member.id', ondelete='CASCADE'))
    revision: Mapped[int] = mapped_column(Integer)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint('announcement_id', 'reader_id'),
        Index('ix_announcement_read_company_reader', 'company_id', 'reader_id'),
    )
