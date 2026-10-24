# services/event_publisher.py
from sqlalchemy import select
from services.event_services import EventService
from core.database import AsyncSessionLocal
from models.group_schemas import FullGroup
from models.group import GroupInvite
from services.connection_manager import manager


async def publish_group_created_event(group: FullGroup, creator_id: int, current_session_id: int):
    """
    group_created — всем участникам группы.
    Создателю — на всех его сессиях, КРОМЕ current_session_id.
    """
    async with AsyncSessionLocal() as db:
        creator_sessions = manager.active_connections.get(creator_id, {})

        for member in group.members:
            user_id = member.user_id
            event_data = {
                "type": "group_created",
                "id": None,
                "data": {"group": group.model_dump(mode="json")},
            }

            if user_id == creator_id:
                for sid in creator_sessions:
                    if sid != current_session_id:
                        await manager.send_personal_message(user_id, event_data, session_id=sid)
                other_sessions = [sid for sid in creator_sessions if sid != current_session_id]
                if other_sessions:
                    await EventService.create_event(db, user_id, event_data, session_ids=other_sessions)
            else:
                await EventService.create_event(db, user_id, event_data)


async def publish_group_invite_created_events(group: FullGroup, creator_id: int):
    """
    group_invite_created — каждому приглашённому (pending) в этой группе.
    Полезная нагрузка минимальна: invite_id, group_id, group_name, inviter_id.
    """
    async with AsyncSessionLocal() as db:
        stmt = select(GroupInvite).where(
            GroupInvite.group_id == group.id,
            GroupInvite.status == "pending",
        )
        invites = (await db.execute(stmt)).scalars().all()

        for inv in invites:
            event_data = {
                "type": "group_invite_created",
                "id": None,
                "data": {
                    "invite_id": inv.id,
                    "group_id": inv.group_id,
                    "group_name": group.name,
                    "inviter_id": creator_id,
                    "created_at": inv.created_at.isoformat() if inv.created_at else None,
                },
            }
            await EventService.create_event(db, inv.invitee_id, event_data)