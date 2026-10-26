from sqlalchemy import Column, BigInteger, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from core.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(BigInteger, primary_key=True, autoincrement=False, nullable=False)
    chat_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    author_session_id = Column(BigInteger, ForeignKey("sessions.id"), nullable=False)
    encrypted = Column(JSONB, nullable=False)
    thread_id = Column(BigInteger, nullable=True)
    edited_at = Column(DateTime(timezone=True), nullable=True)
    deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_messages_chat", "chat_id", "id"),
        Index("idx_messages_author", "author_id"),
        Index("idx_messages_thread", "thread_id", postgresql_where="thread_id IS NOT NULL"),
    )