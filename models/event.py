from sqlalchemy import Column, BigInteger, ForeignKey, DateTime, JSON, ARRAY, Index
from sqlalchemy.sql import func
from core.database import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(BigInteger, primary_key=True, autoincrement=False, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    data = Column(JSON, nullable=False)  # полное событие: {"type": "...", "id": ..., "data": {...}}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session_ids = Column(ARRAY(BigInteger), nullable=False, default=[])  # массив snowflake

    __table_args__ = (
        Index("idx_events_user_id", "user_id", "id"),
        Index("idx_events_session_ids", "session_ids", postgresql_using="gin"),
    )