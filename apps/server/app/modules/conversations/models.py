from datetime import datetime
from app.core.personas import DEFAULT_PERSONA, LEGACY_PERSONA
from app.db.base import Base, Owned, now
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


class Conversation(Owned, Base):
    __tablename__ = 'company_conversation'
    persona_id: Mapped[str] = mapped_column(String(32), default=DEFAULT_PERSONA, server_default=LEGACY_PERSONA)
    title: Mapped[str] = mapped_column(String(120), default='新会话')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
