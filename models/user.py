from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(32), unique=True, nullable=False)
    display_name = Column(String(64))
    avatar_url = Column(Text)
    wall_visibility = Column(String(16), default="public")
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True))
    email = Column(String(255), unique=True)
    bio = Column(Text)
    pronouns = Column(String(32))
    is_bot = Column(Boolean, default=False)