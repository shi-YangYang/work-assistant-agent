from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Owned, now


class AssistantMemory(Owned, Base):
    __tablename__ = 'company_assistant_memory'
    __table_args__ = (UniqueConstraint('company_id', 'owner_id'),)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    document: Mapped[dict] = mapped_column(JSONB, default=lambda: {'schemaVersion': 1, 'markdown': '', 'annotations': []})
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
