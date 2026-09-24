from paa_server.db.base import Base, Owned
from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


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
