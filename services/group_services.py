from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from typing import List

from core.snowflake import generator as snowflake_generator
from core.exceptions import ConflictError, NotFoundError
from models.user import User
from models.group import Group, GroupMember, GroupInvite
from models.group_schemas import FullGroup, GroupMemberInfo


class GroupService:
    @staticmethod
    async def create_group_logic(
        db: AsyncSession, creator_id: int, name: str,
        is_public: bool, public_id: str | None, participant_ids: list[int],
    ) -> FullGroup:
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("Duplicate participant IDs")
        if creator_id in participant_ids:
            raise ValueError("Creator cannot be in participant_ids")

        all_ids = [creator_id] + participant_ids
        stmt = select(User.id).where(User.id.in_(all_ids))
        existing_ids = {row[0] for row in (await db.execute(stmt)).all()}
        missing = set(all_ids) - existing_ids
        if missing:
            raise NotFoundError(f"Users not found: {missing}")

        if is_public:
            if not public_id:
                raise ValueError("public_id is required for public groups")
            stmt = select(Group).where(Group.public_id == public_id)
            if (await db.execute(stmt)).scalar():
                raise ConflictError("public_id already taken")
        else:
            public_id = None

        group_id = await snowflake_generator.generate()
        group = Group(
            id=group_id, public_id=public_id, name=name,
            is_public=is_public, created_by=creator_id,
        )
        db.add(group)
        db.add(GroupMember(group_id=group_id, user_id=creator_id, is_mod=False))

        for uid in participant_ids:
            db.add(GroupInvite(
                id=await snowflake_generator.generate(),
                group_id=group_id, inviter_id=creator_id,
                invitee_id=uid, status="pending",
            ))

        await db.flush()
        await db.refresh(group)

        stmt = select(GroupMember.user_id, GroupMember.is_mod).where(
            GroupMember.group_id == group_id
        )
        rows = (await db.execute(stmt)).all()
        members = [GroupMemberInfo(user_id=r.user_id, is_mod=r.is_mod) for r in rows]

        return FullGroup(
            id=group.id, public_id=group.public_id, name=group.name,
            is_public=group.is_public, created_by=group.created_by,
            created_at=group.created_at, updated_at=group.updated_at,
            members=members, member_count=len(members),
        )

    @staticmethod
    async def create_direct_logic(db, creator_id, other_user_id) -> FullGroup:
        if creator_id == other_user_id:
            raise ValueError("Cannot create direct with yourself")

        creator = (await db.execute(select(User).where(User.id == creator_id))).scalar()
        other_user = (await db.execute(select(User).where(User.id == other_user_id))).scalar()
        if not creator or not other_user:
            raise NotFoundError("User not found")

        raw_other = other_user.display_name or other_user.username
        raw_creator = creator.display_name or creator.username
        group_name = f"{raw_creator.capitalize()} & {raw_other.capitalize()}"

        return await GroupService.create_group_logic(
            db, creator_id=creator_id, name=group_name,
            is_public=False, public_id=None, participant_ids=[other_user_id],
        )

    @staticmethod
    async def _build_full_group(db, group_id: int, is_member: bool, is_public: bool) -> FullGroup:
        group = await db.get(Group, group_id)
        if is_member:
            stmt = select(GroupMember.user_id, GroupMember.is_mod).where(
                GroupMember.group_id == group_id
            )
            rows = (await db.execute(stmt)).all()
            members = [GroupMemberInfo(user_id=r.user_id, is_mod=r.is_mod) for r in rows]
            count = len(members)
        else:
            if not is_public:
                raise NotFoundError("Not a member or group not found")
            members = None
            stmt = select(func.count()).select_from(GroupMember).where(
                GroupMember.group_id == group_id
            )
            count = (await db.execute(stmt)).scalar() or 0

        return FullGroup(
            id=group.id, public_id=group.public_id, name=group.name,
            is_public=group.is_public, created_by=group.created_by,
            created_at=group.created_at, updated_at=group.updated_at,
            members=members, member_count=count,
        )

    @staticmethod
    async def join_group_logic(db, user_id, public_id) -> FullGroup:
        stmt = select(Group).where(Group.public_id == public_id, Group.is_public == True)
        group = (await db.execute(stmt)).scalar()
        if not group:
            raise NotFoundError("Group not found or not public")

        stmt = select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.user_id == user_id
        )
        if (await db.execute(stmt)).scalar():
            raise ConflictError("Already a member")

        db.add(GroupMember(group_id=group.id, user_id=user_id, is_mod=False))
        await db.flush()
        return await GroupService._build_full_group(db, group.id, True, True)

    @staticmethod
    async def leave_group_logic(db, user_id, group_id) -> dict:
        stmt = select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
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
            await db.flush()
            return {"group_id": group_id, "message": "Creator left, group deleted", "deleted": True}

        stmt = select(GroupMember).where(GroupMember.group_id == group_id)
        remaining = (await db.execute(stmt)).scalars().all()
        if not remaining:
            await db.delete(group)
            await db.flush()
            return {"group_id": group_id, "message": "Group deleted (empty)", "deleted": True}

        await db.flush()
        return {"group_id": group_id, "message": "You have left the group", "deleted": False}

    @staticmethod
    async def get_groups_logic(db, user_id) -> List[FullGroup]:
        stmt = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
        group_ids = [row[0] for row in (await db.execute(stmt)).all()]
        return [await GroupService._build_full_group(db, gid, True, True) for gid in group_ids
                if await db.get(Group, gid)]

    @staticmethod
    async def get_group_info_logic(db, user_id, group_id) -> FullGroup:
        group = await db.get(Group, group_id)
        if not group:
            raise NotFoundError("Group not found")

        stmt = select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
        is_member = (await db.execute(stmt)).scalar() is not None
        return await GroupService._build_full_group(db, group_id, is_member, group.is_public)

    @staticmethod
    async def get_invites_logic(db, user_id) -> list[dict]:
        stmt = select(GroupInvite, Group).join(
            Group, GroupInvite.group_id == Group.id
        ).where(GroupInvite.invitee_id == user_id, GroupInvite.status == "pending")
        rows = (await db.execute(stmt)).all()
        return [
            {
                "id": inv.id, "group_id": inv.group_id, "group_name": g.name,
                "inviter_id": inv.inviter_id,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv, g in rows
        ]

    @staticmethod
    async def accept_invite_logic(db, user_id, invite_id) -> dict:
        # FOR UPDATE — защита от race, два параллельных accept не пройдут одновременно
        stmt = select(GroupInvite).where(
            GroupInvite.id == invite_id,
            GroupInvite.invitee_id == user_id,
            GroupInvite.status == "pending",
        ).with_for_update()
        invite = (await db.execute(stmt)).scalar()
        if not invite:
            raise NotFoundError("Invite not found or already processed")

        # Проверка, что уже не член (защита от странных состояний)
        stmt = select(GroupMember).where(
            GroupMember.group_id == invite.group_id, GroupMember.user_id == user_id
        )
        if (await db.execute(stmt)).scalar():
            raise ConflictError("Already a member")

        db.add(GroupMember(group_id=invite.group_id, user_id=user_id, is_mod=False))
        invite.status = "accepted"

        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise ConflictError("Already a member")

        return {"invite_id": invite_id, "group_id": invite.group_id, "status": "accepted"}

    @staticmethod
    async def decline_invite_logic(db, user_id, invite_id) -> dict:
        stmt = select(GroupInvite).where(
            GroupInvite.id == invite_id,
            GroupInvite.invitee_id == user_id,
            GroupInvite.status == "pending",
        ).with_for_update()
        invite = (await db.execute(stmt)).scalar()
        if not invite:
            raise NotFoundError("Invite not found or already processed")

        invite.status = "declined"
        await db.flush()
        return {"invite_id": invite_id, "status": "declined"}