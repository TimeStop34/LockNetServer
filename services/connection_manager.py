import json
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # user_id -> {session_id (из БД): WebSocket}
        self.active_connections: dict[int, dict[int, WebSocket]] = {}

    async def connect(self, user_id: int, session_id: int, ws: WebSocket) -> None:
        if user_id not in self.active_connections:
            self.active_connections[user_id] = {}
        self.active_connections[user_id][session_id] = ws

    def disconnect(self, user_id: int, session_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].pop(session_id, None)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, user_id: int, message: dict, session_id: int | None = None):
        if user_id not in self.active_connections:
            return
        if session_id is not None:
            ws = self.active_connections[user_id].get(session_id)
            if ws:
                try:
                    await ws.send_text(json.dumps(message))
                except:
                    self.disconnect(user_id, session_id)
        else:
            for sid, ws in list(self.active_connections[user_id].items()):
                try:
                    await ws.send_text(json.dumps(message))
                except:
                    self.disconnect(user_id, sid)

    async def broadcast(self, message: dict):
        for user_id, sessions in list(self.active_connections.items()):
            for session_id, ws in list(sessions.items()):
                try:
                    await ws.send_text(json.dumps(message))
                except:
                    self.disconnect(user_id, session_id)

manager = ConnectionManager()