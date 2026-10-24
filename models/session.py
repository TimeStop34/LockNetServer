from sqlalchemy import Column, BigInteger, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func
from core.database import Base

class Session(Base):
    __tablename__ = "sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=False, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(String(64), unique=True, nullable=False)
    access_token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_agent = Column(Text)
    ip_address = Column(INET)