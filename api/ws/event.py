from core.ws import RequestManager, WSEndpointModel
from .router import ws_router
from services.event_services import EventService
from core.database import AsyncSessionLocal
from pydantic import Field


class EventSyncModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)


@ws_router.register("event_sync", EventSyncModel)
async def handle_event_sync(user_id: int, model: EventSyncModel, rm: RequestManager):
    async with AsyncSessionLocal() as db:
        try:
            result = await EventService.sync_events(db, user_id, rm.session_id)
            await rm.send_response("event_sync", model.id, result)
        except Exception as e:
            await rm.send_error("sync_error", f"Event sync failed: {e}", model.id)