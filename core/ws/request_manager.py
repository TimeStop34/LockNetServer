import asyncio
import uuid
import json
from typing import Dict, Any, Optional
from fastapi import WebSocket

class RequestManager:
    """
    Управляет отправкой запросов и ожиданием ответов через WebSocket.
    Привязан к конкретному пользователю и сокету.
    """

    
    def __init__(self, user_id: int, session_id: int, websocket: WebSocket):
        self.user_id = user_id
        self.session_id = session_id
        self.websocket = websocket
        self.pending: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def _generate_id(self) -> str:
        return str(uuid.uuid4())

    async def send_request(self, msg_type: str, data: Dict[str, Any]) -> asyncio.Future:
        req_id = self._generate_id()
        future = asyncio.get_event_loop().create_future()
        async with self._lock:
            self.pending[req_id] = future

        message = {
            "type": msg_type,
            "id": req_id,
            "data": data
        }
        await self.websocket.send_text(json.dumps(message))
        return future

    async def send_response(self, msg_type: str, req_id: str, data: Dict[str, Any]):
        message = {
            "type": f"{msg_type}_ok",
            "id": req_id,
            "data": data
        }
        await self.websocket.send_text(json.dumps(message))

    async def send_error(self, error_code: str, error_msg: str, req_id: Optional[str] = None):
        """
        Отправляет структурированную ошибку.
        - req_id: идентификатор запроса (число или строка)
        - error_code: машинный код (например, "user_not_found")
        - error_msg: человекочитаемое описание
        """
        message = {
            "type": "error",
            "id": req_id,
            "data": {
                "id": error_code,
                "error": error_msg
            }
        }
        await self.websocket.send_text(json.dumps(message))

    async def wait_for_response(self, future: asyncio.Future, timeout: Optional[float] = None) -> Dict[str, Any]:
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                for rid, fut in list(self.pending.items()):
                    if fut is future:
                        self.pending.pop(rid, None)
                        break
            raise

    async def process_message(self, message: dict) -> bool:
        msg_id = message.get("id")
        if msg_id is not None:
            future = self.pending.get(msg_id)
            if future is not None and not future.done():
                future.set_result(message.get("data", {}))
                async with self._lock:
                    self.pending.pop(msg_id, None)
                return True
        return False

    async def request(self, msg_type: str, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        future = await self.send_request(msg_type, data)
        return await self.wait_for_response(future, timeout)