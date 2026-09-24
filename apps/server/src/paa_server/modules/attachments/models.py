from paa_server.db.base import Base, Owned
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


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
