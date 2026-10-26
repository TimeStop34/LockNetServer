from sqlalchemy import Column, BigInteger, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import INET, JSONB
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

    # E2EE (Olm identity keys)
    curve25519_key = Column(Text, nullable=True)
    ed25519_key = Column(Text, nullable=True)

    # Cross-signing signatures: {"<signer_user_id>": {"<signer_key_type>": "<b64sig>"}}
    signatures = Column(JSONB, nullable=False, default=dict)