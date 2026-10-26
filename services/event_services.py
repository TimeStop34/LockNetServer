from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from core.snowflake import generator as snowflake_generator
from models.event import Event
from models.session import Session as SessionModel
from services.connection_manager import manager


class EventService:
    @staticmethod
    async def create_event(
        db: AsyncSession,
        user_id: int,
        event_data: Dict[str, Any],
        session_ids: Optional[List[int]] = None
    ) -> Event:
        """
        Создаёт событие. Если session_ids не задан — все не истёкшие сессии пользователя из БД.
        Активным доставляет сразу (push), офлайн-сессии получат через event_sync.
        """
        if session_ids is None:
            now = datetime.now(timezone.utc)
            stmt = select(SessionModel.id).where(
                SessionModel.user_id == user_id,
                SessionModel.expires_at > now,
            )
            session_ids = [row[0] for row in (await db.execute(stmt)).all()]

        event_id = await snowflake_generator.generate()
        event = Event(
            id=event_id, user_id=user_id,
            data=event_data, session_ids=session_ids,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)

        if session_ids:
            active = manager.active_connections.get(user_id, {})
            delivered: list[int] = []
            for sid in session_ids:
                if sid not in active:
                    continue
                await manager.send_personal_message(user_id, event_data, session_id=sid)
                delivered.append(sid)

            if delivered:
                remaining = [sid for sid in session_ids if sid not in delivered]
                if remaining:
                    stmt = update(Event).where(Event.id == event_id).values(session_ids=remaining)
                    await db.execute(stmt)
                    await db.commit()
                else:
                    await db.delete(event)
                    await db.commit()

        return event

    @staticmethod
    async def sync_events(db: AsyncSession, user_id: int, session_id: int) -> None:
        stmt = select(Event).where(
            Event.user_id == user_id,
            Event.session_ids.any(session_id)
        ).order_by(Event.id.asc())
        result = await db.execute(stmt)
        events = result.scalars().all()

        for event in events:
            await manager.send_personal_message(user_id, event.data, session_id=session_id)
            stmt = update(Event).where(Event.id == event.id).values(
                session_ids=func.array_remove(Event.session_ids, session_id)
            )
            await db.execute(stmt)

        stmt = delete(Event).where(
            Event.user_id == user_id,
            Event.session_ids == []
        )
        await db.execute(stmt)
        await db.commit()