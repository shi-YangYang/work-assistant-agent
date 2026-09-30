from app.db.base import Base, Owned
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class SandboxExecution(Owned, Base):
    __tablename__ = 'company_sandbox_execution'
    key: Mapped[str] = mapped_column(String(64), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('company_job.id'), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('company_conversation.id'), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey('company_message.id'), index=True)
    fence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default='queued')
    code: Mapped[str] = mapped_column(Text)
    request: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
