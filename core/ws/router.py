from typing import Callable, Type, Dict, Any
from pydantic import ValidationError
from .models import WSEndpointModel
from .request_manager import RequestManager

class WSRouter:
    def __init__(self):
        self.handlers: Dict[str, tuple[Callable, Type[WSEndpointModel]]] = {}

    def register(self, msg_type: str, model_class: Type[WSEndpointModel]):
        def decorator(func: Callable):
            self.handlers[msg_type] = (func, model_class)
            return func
        return decorator

    async def handle_message(self, message: dict, user_id: int, request_manager: RequestManager):
        msg_type = message.get("type")
        msg_id = message.get("id")
        msg_data = message.get("data", {})

        if msg_type is None:
            await request_manager.send_error("missing_type", "Missing 'type' field", msg_id)
            return

        if msg_type not in self.handlers:
            await request_manager.send_error("unknown_type", f"Unknown message type: {msg_type}", msg_id)
            return

        handler_func, model_class = self.handlers[msg_type]

        try:
            if msg_id is not None:
                model = model_class(id=msg_id, data=msg_data)
            else:
                model = model_class(data=msg_data)
        except ValidationError as e:
            await request_manager.send_error("validation_error", f"Invalid data: {e.errors()}", msg_id)
            return

        try:
            await handler_func(user_id, model, request_manager)
        except Exception as e:
            await request_manager.send_error("handler_error", f"Handler error: {str(e)}", msg_id)