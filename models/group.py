from sqlalchemy import (
    Column, BigInteger, String, Boolean, DateTime, Text,
    ForeignKey, CheckConstraint, UniqueConstraint, Index
)
from sqlalchemy.sql import func
from core.database import Base

class Group(Base):
    __tablename__ = "groups"

    id = Column(BigInteger, primary_key=True)
    public_id = Column(Text, unique=True, nullable=True)   # может быть NULL для приватных
    name = Column(Text, nullable=False)
    is_public = Column(Boolean, nullable=False, default=True)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "(is_public = TRUE AND public_id IS NOT NULL) OR (is_public = FALSE)",
            name="public_id_required_for_public"
        ),
        Index("idx_groups_public_id", public_id, unique=True, postgresql_where=public_id.isnot(None)),
        Index("idx_groups_is_public", is_public),
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    is_mod = Column(Boolean, default=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_group_members_user", user_id),
        Index("idx_group_members_mod", group_id, is_mod, postgresql_where=(is_mod == True)),
    )


class GroupInvite(Base):
    __tablename__ = "group_invites"

    id = Column(BigInteger, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    inviter_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    invitee_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    status = Column(String(16), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("group_id", "invitee_id", name="uq_group_invite_pair"),
        Index("idx_group_invites_invitee", invitee_id, status),
        Index("idx_group_invites_group", group_id, status),
    )