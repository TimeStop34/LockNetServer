from sqlalchemy import Column, BigInteger, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from core.database import Base


class KeyBackupVersion(Base):
    __tablename__ = "key_backup_versions"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    version = Column(Integer, primary_key=True)
    algorithm = Column(String(64), nullable=False)
    auth_data = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KeyBackupItem(Base):
    __tablename__ = "key_backup_items"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    version = Column(Integer, primary_key=True)
    item_id = Column(String, primary_key=True)   # "chat_id:megolm_session_id"
    data = Column(JSONB, nullable=False)         # {"nonce": ..., "ciphertext": ...}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_key_backup_user_version", "user_id", "version"),
    )