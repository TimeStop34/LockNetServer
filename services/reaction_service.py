from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from models.message import Message
from models.reaction import Reaction
from models.group import GroupMember
from core.exceptions import NotFoundError, UnauthorizedError
from services.event_publisher import publish_to_group


class ReactionService:

    @staticmethod
    async def add(
        db: AsyncSession,
        user_id: int,
        message_id: int,
        emoji: str,
    ) -> dict:
        if not emoji or len(emoji) < 1 or len(emoji) > 64:
            raise ValueError("invalid_emoji")

        msg = await db.get(Message, message_id)
        if not msg:
            raise NotFoundError("message_not_found")
        if msg.deleted:
            raise ValueError("message_deleted")

        stmt = select(GroupMember).where(
            GroupMember.group_id == msg.chat_id,
            GroupMember.user_id == user_id,
        )
        if (await db.execute(stmt)).scalar() is None:
            raise UnauthorizedError("not_a_member")

        react = Reaction(message_id=message_id, user_id=user_id, emoji=emoji)
        db.add(react)
        try:
            await db.commit()
            inserted = True
        except IntegrityError:
            await db.rollback()
            inserted = False

        if inserted:
            event_data = {
                "type": "reaction_add",
                "id": None,
                "data": {
                    "message_id": message_id,
                    "chat_id": msg.chat_id,
                    "user_id": user_id,
                    "emoji": emoji,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            await publish_to_group(msg.chat_id, event_data)

        return {"message_id": message_id, "emoji": emoji, "inserted": inserted}

    @staticmethod
    async def remove(
        db: AsyncSession,
        user_id: int,
        message_id: int,
        emoji: str,
    ) -> dict:
        msg = await db.get(Message, message_id)
        if not msg:
            raise NotFoundError("message_not_found")

        stmt = select(Reaction).where(
            Reaction.message_id == message_id,
            Reaction.user_id == user_id,
            Reaction.emoji == emoji,
        )
        react = (await db.execute(stmt)).scalar()
        if not react:
            raise NotFoundError("reaction_not_found")

        await db.delete(react)
        await db.commit()

        event_data = {
            "type": "reaction_remove",
            "id": None,
            "data": {
                "message_id": message_id,
                "chat_id": msg.chat_id,
                "user_id": user_id,
                "emoji": emoji,
            },
        }
        await publish_to_group(msg.chat_id, event_data)
        return {"message_id": message_id, "emoji": emoji}