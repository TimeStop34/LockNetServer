import json
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from core.database import AsyncSessionLocal
from services.connection_manager import manager
from services.auth_service import AuthService
from core import security
from core.ws import RequestManager
from .ws import ws_router
from sqlalchemy import select
from models.session import Session as SessionModel

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Ожидаем первое сообщение — оно должно быть auth
    try:
        raw = await websocket.receive_text()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"id": "invalid_json", "error": "Invalid JSON"}
            }))
            await websocket.close(code=1003, reason="Invalid JSON")
            return

        # Проверяем, что это auth
        if msg.get("type") != "auth":
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"id": "auth_required", "error": "First message must be auth"}
            }))
            await websocket.close(code=1008, reason="First message must be auth")
            return

        token = msg.get("data", {}).get("token")
        if not token:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"id": "token_missing", "error": "Token missing in auth"}
            }))
            await websocket.close(code=1008, reason="Token missing")
            return

        # Проверяем токен через БД
        async with AsyncSessionLocal() as db:
            valid = await AuthService.verify_token(db, token, is_refresh=False)
            if not valid:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"id": "invalid_token", "error": "Invalid token"}
                }))
                await websocket.close(code=1008, reason="Invalid token")
                return

            try:
                payload = security.decode_jwt(token)
                user_id = int(payload["sub"])
            except Exception:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"id": "invalid_token", "error": "Invalid token"}
                }))
                await websocket.close(code=1008, reason="Invalid token")
                return

            # Находим session_id
            token_hash = security.generate_token_hash(token)
            stmt = select(SessionModel.id).where(SessionModel.access_token_hash == token_hash)
            session_id = (await db.execute(stmt)).scalar()
            if not session_id:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"id": "session_not_found", "error": "Session not found"}
                }))
                await websocket.close(code=1008, reason="Session not found")
                return

            # Успешная аутентификация — отвечаем auth_ok
            await websocket.send_text(json.dumps({
                "type": "auth_ok",
                "id": msg.get("id"),
                "data": {}
            }))

            # Подключаем менеджер и создаём RequestManager
            await manager.connect(user_id, session_id, websocket)
            request_manager = RequestManager(user_id, session_id, websocket)

            # Входим в основной цикл обработки сообщений
            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        msg = json.loads(data)
                    except json.JSONDecodeError:
                        await request_manager.send_error("invalid_json", "Invalid JSON", None)
                        continue

                    # Если сообщение — повторный auth — игнорируем или закрываем?
                    # Лучше игнорировать, чтобы не мешать
                    if msg.get("type") == "auth":
                        continue

                    if await request_manager.process_message(msg):
                        continue

                    await ws_router.handle_message(msg, user_id, request_manager)

            except WebSocketDisconnect:
                manager.disconnect(user_id, session_id)

    except WebSocketDisconnect:
        # Клиент закрыл соединение до отправки auth
        return