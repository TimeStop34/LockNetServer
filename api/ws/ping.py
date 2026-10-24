from datetime import datetime, timezone
import time
from core.ws import RequestManager, WSEndpointModel
from .router import ws_router

class PingModel(WSEndpointModel):
    pass

@ws_router.register("ping", PingModel)
async def handle_ping(user_id: int, model: PingModel, rm: RequestManager):
    await rm.send_response("ping", model.id, {"pong": True, "time": datetime.now(timezone.utc).isoformat()})