from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from core.config import logger
from core.snowflake import generator as snowflake_generator
from core.exceptions import ConflictError, NotFoundError
from models.user import User
from models.group import Group, GroupMember, GroupInvite
from models.group_schemas import FullGroup, GroupMemberInfo


class GroupService:
    @staticmethod
    async def create_group_logic(
        db: AsyncSession,
        creator_id: int,
        name: str,
        is_public: bool,
        public_id: str | None,
        participant_ids: list[int]
    ) -> FullGroup:
        """
        Универсальный метод создания группы.
        Создатель добавляется как участник, остальные получают приглашения.
        """
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("Duplicate participant IDs")

        if creator_id in participant_ids:
            raise ValueError("Creator cannot be in participant_ids")

        all_ids = [creator_id] + participant_ids
        stmt = select(User.id).where(User.id.in_(all_ids))
        result = await db.execute(stmt)
        existing_ids = {row[0] for row in result.all()}
        missing = set(all_ids) - existing_ids
        if missing:
            raise NotFoundError(f"Users not found: {missing}")

        if is_public:
            if not public_id:
                raise ValueError("public_id is required for public groups")
            stmt = select(Group).where(Group.public_id == public_id)
            existing = await db.execute(stmt)
            if existing.scalar():
                raise ConflictError("public_id already taken")
        else:
            public_id = None

        group_id = await snowflake_generator.generate()
        group = Group(
            id=group_id,
            public_id=public_id,
            name=name,
            is_public=is_public,
            created_by=creator_id
        )
        db.add(group)

        # Создатель всегда становится участником (не модератором)
        creator_member = GroupMember(
            group_id=group_id,
            user_id=creator_id,
            is_mod=False
        )
        db.add(creator_member)

        # Остальные получают приглашения
        for uid in participant_ids:
            invite = GroupInvite(
                id=await snowflake_generator.generate(),
                group_id=group_id,
                inviter_id=creator_id,
                invitee_id=uid,
                status="pending"
            )
            db.add(invite)

        await db.commit()
        await db.refresh(group)

        stmt = select(GroupMember.user_id, GroupMember.is_mod).where(GroupMember.group_id == group_id)
        rows = (await db.execute(stmt)).all()
        members = [GroupMemberInfo(user_id=r.user_id, is_mod=r.is_mod) for r in rows]
        member_count = len(members)

        return FullGroup(
            id=group.id,
            public_id=group.public_id,
            name=group.name,
            is_public=group.is_public,
            created_by=group.created_by,
            created_at=group.created_at,
            updated_at=group.updated_at,
            members=members,
            member_count=member_count
        )

    @staticmethod
    async def create_direct_logic(
        db: AsyncSession,
        creator_id: int,
        other_user_id: int
    ) -> FullGroup:
        """
        Создаёт личную переписку (ЛС).
        Имя группы = display_name другого пользователя (или username, если display_name отсутствует).
        Создатель добавляется как участник, другой пользователь получает приглашение.
        """
        if creator_id == other_user_id:
            raise ValueError("Cannot create direct with yourself")

        stmt = select(User).where(User.id == creator_id)
        creator = (await db.execute(stmt)).scalar()
        if not creator:
            raise NotFoundError("User not found")

        stmt = select(User).where(User.id == other_user_id)
        other_user = (await db.execute(stmt)).scalar()
        if not other_user:
            raise NotFoundError("User not found")

        raw_other_user_name: str = other_user.display_name or other_user.username
        raw_creator_name: str = creator.display_name or creator.username
        group_name = f"{raw_creator_name.capitalize()} & {raw_other_user_name.capitalize()}"

        return await GroupService.create_group_logic(
            db,
            creator_id=creator_id,
            name=group_name,
            is_public=False,
            public_id=None,
            participant_ids=[other_user_id]
        )

    @staticmethod
    async def join_group_logic(db: AsyncSession, user_id: int, public_id: str) -> FullGroup:
        stmt = select(Group).where(
            Group.public_id == public_id,
            Group.is_public == True
        )
        result = await db.execute(stmt)
        group = result.scalar()
        if not group:
            raise NotFoundError("Group not found or not public")

        stmt = select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == user_id
        )
        existing = await db.execute(stmt)
        if existing.scalar():
            raise ConflictError("Already a member")

        member = GroupMember(group_id=group.id, user_id=user_id, is_mod=False)
        db.add(member)
        await db.commit()
        await db.refresh(group)

        stmt = select(GroupMember.user_id, GroupMember.is_mod).where(GroupMember.group_id == group.id)
        rows = (await db.execute(stmt)).all()
        members = [GroupMemberInfo(user_id=r.user_id, is_mod=r.is_mod) for r in rows]
        member_count = len(members)

        return FullGroup(
            id=group.id,
            public_id=group.public_id,
            name=group.name,
            is_public=group.is_public,
            created_by=group.created_by,
            created_at=group.created_at,
            updated_at=group.updated_at,
            members=members,
            member_count=member_count
        )

    @staticmethod
    async def leave_group_logic(db: AsyncSession, user_id: int, group_id: int) -> dict:
        stmt = select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id
        )
        member = (await db.execute(stmt)).scalar()
        if not member:
            raise NotFoundError("Not a member")

        group = await db.get(Group, group_id)
        if not group:
            raise NotFoundError("Group not found")

        is_creator = (group.created_by == user_id)

        await db.delete(member)

        if is_creator:
            await db.delete(group)
            await db.commit()
            return {"group_id": group_id, "message": "Creator left, group deleted", "deleted": True}

        stmt = select(GroupMember).where(GroupMember.group_id == group_id)
        remaining = (await db.execute(stmt)).scalars().all()
        if not remaining:
            await db.delete(group)
            await db.commit()
            return {"group_id": group_id, "message": "Group deleted (empty)", "deleted": True}

        await db.commit()
        return {"group_id": group_id, "message": "You have left the group", "deleted": False}

    @staticmethod
    async def get_groups_logic(db: AsyncSession, user_id: int) -> List[FullGroup]:
        stmt = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
        group_ids = [row[0] for row in (await db.execute(stmt)).all()]

        if not group_ids:
            return []

        groups = []
        for gid in group_ids:
            group = await db.get(Group, gid)
            if not group:
                continue
            stmt = select(GroupMember.user_id, GroupMember.is_mod).where(GroupMember.group_id == gid)
            rows = (await db.execute(stmt)).all()
            members = [GroupMemberInfo(user_id=r.user_id, is_mod=r.is_mod) for r in rows]
            member_count = len(members)
            groups.append(FullGroup(
                id=group.id,
                public_id=group.public_id,
                name=group.name,
                is_public=group.is_public,
                created_by=group.created_by,
                created_at=group.created_at,
                updated_at=group.updated_at,
                members=members,
                member_count=member_count
            ))
        return groups

    @staticmethod
    async def get_group_info_logic(db: AsyncSession, user_id: int, group_id: int) -> FullGroup:
        group = await db.get(Group, group_id)
        if not group:
            raise NotFoundError("Group not found")

        stmt = select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id
        )
        is_member = (await db.execute(stmt)).scalar() is not None

        if is_member:
            stmt = select(GroupMember.user_id, GroupMember.is_mod).where(GroupMember.group_id == group_id)
            rows = (await db.execute(stmt)).all()
            members = [GroupMemberInfo(user_id=r.user_id, is_mod=r.is_mod) for r in rows]
            member_count = len(members)
        else:
            if not group.is_public:
                raise NotFoundError("Not a member or group not found")
            members = None
            stmt = select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
            member_count = (await db.execute(stmt)).scalar() or 0

        return FullGroup(
            id=group.id,
            public_id=group.public_id,
            name=group.name,
            is_public=group.is_public,
            created_by=group.created_by,
            created_at=group.created_at,
            updated_at=group.updated_at,
            members=members,
            member_count=member_count
        )

    @staticmethod
    async def get_invites_logic(db: AsyncSession, user_id: int) -> list[dict]:
        """Возвращает список входящих приглашений для пользователя."""
        stmt = select(GroupInvite, Group).join(
            Group, GroupInvite.group_id == Group.id
        ).where(
            GroupInvite.invitee_id == user_id,
            GroupInvite.status == "pending"
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "id": invite.id,
                "group_id": invite.group_id,
                "group_name": group.name,
                "inviter_id": invite.inviter_id,
                "created_at": invite.created_at.isoformat() if invite.created_at else None
            }
            for invite, group in rows
        ]

    @staticmethod
    async def accept_invite_logic(db: AsyncSession, user_id: int, invite_id: int) -> dict:
        """Принимает приглашение: добавляет в группу, меняет статус."""
        stmt = select(GroupInvite).where(
            GroupInvite.id == invite_id,
            GroupInvite.invitee_id == user_id,
            GroupInvite.status == "pending"
        )
        invite = (await db.execute(stmt)).scalar()
        if not invite:
            raise NotFoundError("Invite not found or already processed")

        stmt = select(GroupMember).where(
            GroupMember.group_id == invite.group_id,
            GroupMember.user_id == user_id
        )
        if (await db.execute(stmt)).scalar():
            raise ConflictError("Already a member")

        member = GroupMember(group_id=invite.group_id, user_id=user_id, is_mod=False)
        db.add(member)
        invite.status = "accepted"
        await db.commit()
        return {"invite_id": invite_id, "group_id": invite.group_id, "status": "accepted"}

    @staticmethod
    async def decline_invite_logic(db: AsyncSession, user_id: int, invite_id: int) -> dict:
        """Отклоняет приглашение."""
        stmt = select(GroupInvite).where(
            GroupInvite.id == invite_id,
            GroupInvite.invitee_id == user_id,
            GroupInvite.status == "pending"
        )
        invite = (await db.execute(stmt)).scalar()
        if not invite:
            raise NotFoundError("Invite not found or already processed")

        invite.status = "declined"
        await db.commit()
        return {"invite_id": invite_id, "status": "declined"}