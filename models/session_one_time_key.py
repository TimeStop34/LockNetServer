from sqlalchemy import Column, BigInteger, String, ForeignKey, Index
from core.database import Base

class SessionOneTimeKey(Base):
    __tablename__ = "session_one_time_keys"

    session_id = Column(BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    key_id = Column(String, primary_key=True)
    key_value = Column(String, nullable=False)
    algorithm = Column(String, nullable=False, default="curve25519")

    __table_args__ = (
        Index("idx_otk_session", "session_id"),
    )