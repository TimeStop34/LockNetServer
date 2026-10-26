from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from core.database import Base


class Reaction(Base):
    __tablename__ = "reactions"

    message_id = Column(BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    emoji = Column(String(64), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_reactions_message", "message_id"),
    )