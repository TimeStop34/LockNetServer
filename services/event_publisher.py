# services/event_publisher.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any

from core.snowflake import generator as snowflake_generator
from services.event_services import EventService
from core.database import AsyncSessionLocal
from models.group_schemas import FullGroup
from models.group import GroupInvite, GroupMember


async def publish_event(user_ids: List[int], event: Dict[str, Any]) -> int:
    """
    Публикует событие указанным пользователям. Один event_id в data.id
    для всех получателей — клиент дедуплицирует по нему.
    """
    event_id = event.get("id")
    if event_id is None:
        event_id = await snowflake_generator.generate()
        event = {**event, "id": event_id}

    async with AsyncSessionLocal() as db:
        for uid in user_ids:
            await EventService.create_event(db, uid, event)

    return event_id


async def publish_to_group(chat_id: int, event: Dict[str, Any]) -> int:
    """Публикует всем актуальным участникам группы."""
    async with AsyncSessionLocal() as db:
        stmt = select(GroupMember.user_id).where(GroupMember.group_id == chat_id)
        user_ids = [row[0] for row in (await db.execute(stmt)).all()]
    return await publish_event(user_ids, event)


async def publish_group_created_event(group: FullGroup, creator_id: int, current_session_id: int):
    """
    group_created — всем участникам (на момент создания только создатель).
    Создателю — на всех сессиях, кроме current_session_id.
    """
    event_data = {
        "type": "group_created",
        "id": None,
        "data": {"group": group.model_dump(mode="json")},
    }
    event_id = await snowflake_generator.generate()
    event_data["id"] = event_id

    async with AsyncSessionLocal() as db:
        from datetime import datetime, timezone
        from models.session import Session as SessionModel

        now = datetime.now(timezone.utc)
        stmt = select(SessionModel.id).where(
            SessionModel.user_id == creator_id,
            SessionModel.expires_at > now,
            SessionModel.id != current_session_id,
        )
        other_sessions = [row[0] for row in (await db.execute(stmt)).all()]
        if other_sessions:
            await EventService.create_event(db, creator_id, event_data, session_ids=other_sessions)

    # Остальные участники (на создании их нет, но код общий)
    for member in group.members:
        if member.user_id == creator_id:
            continue
        async with AsyncSessionLocal() as db:
            await EventService.create_event(db, member.user_id, event_data)


async def publish_group_invite_created_events(group: FullGroup, creator_id: int):
    async with AsyncSessionLocal() as db:
        stmt = select(GroupInvite).where(
            GroupInvite.group_id == group.id,
            GroupInvite.status == "pending",
        )
        invites = (await db.execute(stmt)).scalars().all()

        for inv in invites:
            event_id = await snowflake_generator.generate()
            event_data = {
                "type": "group_invite_created",
                "id": event_id,
                "data": {
                    "invite_id": inv.id,
                    "group_id": inv.group_id,
                    "group_name": group.name,
                    "inviter_id": creator_id,
                    "created_at": inv.created_at.isoformat() if inv.created_at else None,
                },
            }
            await EventService.create_event(db, inv.invitee_id, event_data)