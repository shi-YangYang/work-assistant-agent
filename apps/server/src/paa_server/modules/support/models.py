from datetime import datetime
from paa_server.db.base import Base, Owned, now
from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


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
