from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import List

from core.config import settings
from core.snowflake import generator as snowflake_generator
from core.exceptions import NotFoundError, UnauthorizedError
from models.session import Session as SessionModel
from models.group import GroupMember, Group
from models.message import Message
from models.reaction import Reaction
from services.event_services import EventService
from services.rate_limiter import message_rate_limiter


REQUIRED_ENCRYPTED_FIELDS = ("algorithm", "sender_key", "sender_session_id", "megolm_session_id", "ciphertext")


class MessageService:

    @staticmethod
    def _validate_encrypted(encrypted: dict, current_session_id: int) -> None:
        if not isinstance(encrypted, dict):
            raise ValueError("invalid_encrypted")
        for f in REQUIRED_ENCRYPTED_FIELDS:
            if f not in encrypted:
                raise ValueError(f"invalid_encrypted: missing {f}")
        if int(encrypted["sender_session_id"]) != current_session_id:
            raise ValueError("session_mismatch")
        try:
            cipher_len = len(str(encrypted["ciphertext"]).encode("utf-8"))
        except Exception:
            raise ValueError("invalid_encrypted")
        if cipher_len > settings.MESSAGE_MAX_BYTES:
            raise ValueError("message_too_large")

    @staticmethod
    async def _ensure_member(db: AsyncSession, chat_id: int, user_id: int) -> None:
        group = await db.get(Group, chat_id)
        if not group:
            raise NotFoundError("chat_not_found")
        stmt = select(GroupMember).where(
            GroupMember.group_id == chat_id,
            GroupMember.user_id == user_id,
        )
        if (await db.execute(stmt)).scalar() is None:
            raise UnauthorizedError("not_a_member")

    @staticmethod
    async def _message_row_to_dict(msg: Message, reactions: list) -> dict:
        return {
            "message_id": msg.id,
            "chat_id": msg.chat_id,
            "author_id": msg.author_id,
            "author_session_id": msg.author_session_id,
            "encrypted": None if msg.deleted else msg.encrypted,
            "thread_id": msg.thread_id,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
            "deleted": bool(msg.deleted),
            "reactions": reactions,
        }

    @staticmethod
    async def _load_sender_session(db: AsyncSession, user_id: int, session_id: int) -> SessionModel:
        session = await db.get(SessionModel, session_id)
        if not session or session.user_id != user_id:
            raise UnauthorizedError("Session not found")
        return session

    @staticmethod
    def _rewrite_sender_fields(encrypted: dict, sender_session: SessionModel) -> dict:
        if not sender_session.curve25519_key:
            raise ValueError("Sender has no curve25519_key — upload_keys first")
        safe = dict(encrypted or {})
        safe["sender_key"] = sender_session.curve25519_key
        safe["sender_session_id"] = sender_session.id
        return safe

    @staticmethod
    async def send(
        db: AsyncSession,
        user_id: int,
        session_id: int,
        chat_id: int,
        encrypted: dict,
    ) -> dict:
        await MessageService._ensure_member(db, chat_id, user_id)
        MessageService._validate_encrypted(encrypted, session_id)

        if not message_rate_limiter.check(f"msg:{session_id}", settings.MESSAGE_RATE_LIMIT_PER_MINUTE):
            raise ValueError("rate_limited")

        sender_session = await MessageService._load_sender_session(db, user_id, session_id)
        safe_encrypted = MessageService._rewrite_sender_fields(encrypted, sender_session)

        message_id = await snowflake_generator.generate()
        msg = Message(
            id=message_id,
            chat_id=chat_id,
            author_id=user_id,
            author_session_id=session_id,
            encrypted=safe_encrypted,
            thread_id=None,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        event_data = {
            "type": "message_create",
            "id": message_id,
            "data": {
                "message_id": message_id,
                "chat_id": chat_id,
                "author_id": user_id,
                "author_session_id": session_id,
                "encrypted": safe_encrypted,
                "thread_id": None,
                "created_at": msg.created_at.isoformat(),
                "edited_at": None,
                "reactions": [],
            },
        }

        now = datetime.now(timezone.utc)
        stmt = select(GroupMember.user_id).where(GroupMember.group_id == chat_id)
        member_ids = [row[0] for row in (await db.execute(stmt)).all()]

        for member_uid in member_ids:
            if member_uid == user_id:
                stmt = select(SessionModel.id).where(
                    SessionModel.user_id == member_uid,
                    SessionModel.expires_at > now,
                    SessionModel.id != session_id,
                )
            else:
                stmt = select(SessionModel.id).where(
                    SessionModel.user_id == member_uid,
                    SessionModel.expires_at > now,
                )
            target_sessions = [row[0] for row in (await db.execute(stmt)).all()]
            if target_sessions:
                await EventService.create_event(db, member_uid, event_data, session_ids=target_sessions)

        return {"message_id": message_id, "created_at": msg.created_at.isoformat()}

    @staticmethod
    async def get_messages(
        db: AsyncSession,
        user_id: int,
        chat_id: int,
        before: int | None,
        limit: int,
    ) -> dict:
        await MessageService._ensure_member(db, chat_id, user_id)
        if limit < 1 or limit > 100:
            raise ValueError("invalid_limit")

        stmt = select(Message).where(Message.chat_id == chat_id)
        if before is not None:
            stmt = stmt.where(Message.id < before)
        stmt = stmt.order_by(Message.id.desc()).limit(limit + 1)
        rows = (await db.execute(stmt)).scalars().all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        message_ids = [m.id for m in rows]
        agg = defaultdict(lambda: defaultdict(list))
        if message_ids:
            rstmt = select(Reaction.message_id, Reaction.user_id, Reaction.emoji).where(
                Reaction.message_id.in_(message_ids)
            )
            for mid, uid, emoji in (await db.execute(rstmt)).all():
                agg[mid][emoji].append(uid)

        result = []
        for m in rows:
            reactions = [
                {"emoji": e, "count": len(uids), "user_ids": uids}
                for e, uids in agg.get(m.id, {}).items()
            ]
            result.append(await MessageService._message_row_to_dict(m, reactions))

        return {"messages": result, "has_more": has_more}

    @staticmethod
    async def edit(
        db: AsyncSession,
        user_id: int,
        session_id: int,
        message_id: int,
        encrypted: dict,
    ) -> dict:
        msg = await db.get(Message, message_id)
        if not msg:
            raise NotFoundError("message_not_found")
        if msg.author_id != user_id:
            raise UnauthorizedError("not_author")
        if msg.deleted:
            raise ValueError("message_deleted")

        window_end = msg.created_at + timedelta(hours=settings.MESSAGE_EDIT_WINDOW_HOURS)
        if datetime.now(timezone.utc) > window_end:
            raise ValueError("edit_window_expired")

        MessageService._validate_encrypted(encrypted, session_id)

        sender_session = await MessageService._load_sender_session(db, user_id, session_id)
        safe_encrypted = MessageService._rewrite_sender_fields(encrypted, sender_session)

        msg.encrypted = safe_encrypted
        msg.edited_at = datetime.now(timezone.utc)
        await db.commit()

        event_data = {
            "type": "message_update",
            "id": msg.id,
            "data": {
                "message_id": msg.id,
                "chat_id": msg.chat_id,
                "encrypted": safe_encrypted,
                "edited_at": msg.edited_at.isoformat(),
            },
        }
        from services.event_publisher import publish_to_group
        await publish_to_group(msg.chat_id, event_data)
        return {"message_id": msg.id, "edited_at": msg.edited_at.isoformat()}

    @staticmethod
    async def delete(
        db: AsyncSession,
        user_id: int,
        message_id: int,
    ) -> dict:
        msg = await db.get(Message, message_id)
        if not msg:
            raise NotFoundError("message_not_found")

        if msg.author_id != user_id:
            stmt = select(GroupMember).where(
                GroupMember.group_id == msg.chat_id,
                GroupMember.user_id == user_id,
                GroupMember.is_mod == True,
            )
            if (await db.execute(stmt)).scalar() is None:
                raise UnauthorizedError("forbidden")

        if not msg.deleted:
            msg.deleted = True
            msg.deleted_at = datetime.now(timezone.utc)
            await db.commit()

            event_data = {
                "type": "message_delete",
                "id": msg.id,
                "data": {"message_id": msg.id, "chat_id": msg.chat_id},
            }
            from services.event_publisher import publish_to_group
            await publish_to_group(msg.chat_id, event_data)

        return {"message_id": msg.id}

    @staticmethod
    async def send_to_device(
        db: AsyncSession,
        sender_user_id: int,
        sender_session_id: int,
        messages: dict,
    ) -> dict:
        """
        Доставка to-device (Olm) события конкретным сессиям.
        Сервер не расшифровывает. Подменяет sender_session_id и sender_key
        на данные аутентифицированной сессии — защита от подмены.
        """
        sender_session = await MessageService._load_sender_session(
            db, sender_user_id, sender_session_id
        )
        if not sender_session.curve25519_key:
            raise ValueError("Sender has no curve25519_key — upload_keys first")

        accepted = 0
        dropped = 0

        for target_uid_str, sessions_dict in (messages or {}).items():
            try:
                target_uid = int(target_uid_str)
            except (ValueError, TypeError):
                dropped += 1
                continue

            if not isinstance(sessions_dict, dict):
                dropped += 1
                continue

            for target_sid_str, olm_payload in sessions_dict.items():
                try:
                    target_sid = int(target_sid_str)
                except (ValueError, TypeError):
                    dropped += 1
                    continue

                target_session = await db.get(SessionModel, target_sid)
                if not target_session or target_session.user_id != target_uid:
                    dropped += 1
                    continue

                if not isinstance(olm_payload, dict):
                    dropped += 1
                    continue

                safe_payload = dict(olm_payload)
                safe_payload["sender_session_id"] = sender_session_id
                safe_payload["sender_key"] = sender_session.curve25519_key

                event_data = {
                    "type": "to_device",
                    "id": None,
                    "data": safe_payload,
                }
                await EventService.create_event(
                    db, target_uid, event_data, session_ids=[target_sid]
                )
                accepted += 1

        return {"accepted": accepted, "dropped": dropped}