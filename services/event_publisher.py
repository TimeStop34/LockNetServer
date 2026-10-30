from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from datetime import datetime, timezone

from core.snowflake import generator as snowflake_generator
from services.event_services import EventService
from models.group_schemas import FullGroup
from models.group import GroupInvite, GroupMember
from models.session import Session as SessionModel


async def publish_event(db: AsyncSession, user_ids: List[int], event: Dict[str, Any]) -> int:
    event_id = event.get("id")
    if event_id is None:
        event_id = await snowflake_generator.generate()
        event = {**event, "id": event_id}

    for uid in user_ids:
        await EventService.create_event(db, uid, event)

    return event_id


async def publish_to_group(db: AsyncSession, chat_id: int, event: Dict[str, Any]) -> int:
    stmt = select(GroupMember.user_id).where(GroupMember.group_id == chat_id)
    user_ids = [row[0] for row in (await db.execute(stmt)).all()]
    return await publish_event(db, user_ids, event)


async def publish_group_created_event(
    db: AsyncSession, group: FullGroup, creator_id: int, current_session_id: int,
) -> None:
    event_id = await snowflake_generator.generate()
    event_data = {
        "type": "group_created",
        "id": event_id,
        "data": {"group": group.model_dump(mode="json")},
    }

    now = datetime.now(timezone.utc)
    stmt = select(SessionModel.id).where(
        SessionModel.user_id == creator_id,
        SessionModel.expires_at > now,
        SessionModel.id != current_session_id,
    )
    other_sessions = [row[0] for row in (await db.execute(stmt)).all()]
    if other_sessions:
        await EventService.create_event(db, creator_id, event_data, session_ids=other_sessions)

    for member in group.members:
        if member.user_id == creator_id:
            continue
        await EventService.create_event(db, member.user_id, event_data)


async def publish_group_invite_created_events(
    db: AsyncSession, group: FullGroup, creator_id: int,
) -> None:
    stmt = select(GroupInvite).where(
        GroupInvite.group_id == group.id,
        GroupInvite.status == "pending",
    )
    invites = (await db.execute(stmt)).scalars().all()

    for inv in invites:
        event_data = {
            "type": "group_invite_created",
            "id": await snowflake_generator.generate(),
            "data": {
                "invite_id": inv.id,
                "group_id": inv.group_id,
                "group_name": group.name,
                "inviter_id": creator_id,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            },
        }
        await EventService.create_event(db, inv.invitee_id, event_data)