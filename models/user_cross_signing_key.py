from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from core.database import Base

class UserCrossSigningKey(Base):
    __tablename__ = "user_cross_signing_keys"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key_type = Column(String, primary_key=True)  # "master" | "self_signing" | "user_signing"
    key_value = Column(String, nullable=False)
    signatures = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())