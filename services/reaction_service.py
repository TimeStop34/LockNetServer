from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timezone

from models.message import Message
from models.reaction import Reaction
from models.group import GroupMember
from core.exceptions import NotFoundError, UnauthorizedError
from services.event_publisher import publish_to_group


class ReactionService:

    @staticmethod
    async def add(db, user_id, message_id, emoji) -> dict:
        if not emoji or len(emoji) < 1 or len(emoji) > 64:
            raise ValueError("invalid_emoji")

        msg = await db.get(Message, message_id)
        if not msg:
            raise NotFoundError("message_not_found")
        if msg.deleted:
            raise ValueError("message_deleted")

        stmt = select(GroupMember).where(
            GroupMember.group_id == msg.chat_id, GroupMember.user_id == user_id,
        )
        if (await db.execute(stmt)).scalar() is None:
            raise UnauthorizedError("not_a_member")

        # ON CONFLICT DO NOTHING — без IntegrityError/rollback
        stmt = pg_insert(Reaction).values(
            message_id=message_id, user_id=user_id, emoji=emoji,
        ).on_conflict_do_nothing()
        result = await db.execute(stmt)
        inserted = result.rowcount > 0
        await db.flush()

        if inserted:
            event_data = {
                "type": "reaction_add", "id": None,
                "data": {
                    "message_id": message_id, "chat_id": msg.chat_id,
                    "user_id": user_id, "emoji": emoji,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            await publish_to_group(db, msg.chat_id, event_data)

        await db.commit()
        return {"message_id": message_id, "emoji": emoji, "inserted": inserted}

    @staticmethod
    async def remove(db, user_id, message_id, emoji) -> dict:
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
        await db.flush()

        event_data = {
            "type": "reaction_remove", "id": None,
            "data": {
                "message_id": message_id, "chat_id": msg.chat_id,
                "user_id": user_id, "emoji": emoji,
            },
        }
        await publish_to_group(db, msg.chat_id, event_data)
        await db.commit()
        return {"message_id": message_id, "emoji": emoji}