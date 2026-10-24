from fastapi import APIRouter
from pydantic import BaseModel
from core import security
from core.config import settings
from core.database import AsyncSessionLocal
from sqlalchemy import select
from models.user import User
from models.session import Session as SessionModel
import jwt
import time

router = APIRouter(prefix="/api/v1/jwt", tags=["jwt"])


class JWTKCheckRequest(BaseModel):
    token: str


@router.post("/kcheck")
async def jwt_kcheck(request_data: JWTKCheckRequest):
    token = request_data.token

    try:
        payload = security.decode_jwt(token)
    except jwt.InvalidTokenError:
        return {"valid": False, "reason": "invalid_token"}

    required_fields = ["sub", "space", "iat", "exp", "type"]
    for field in required_fields:
        if field not in payload:
            return {"valid": False, "reason": "missing_field"}

    if payload["space"] != settings.SPACE:
        return {"valid": False, "reason": "space_mismatch"}

    if payload["iat"] >= payload["exp"]:
        return {"valid": False, "reason": "invalid_time_epoch"}

    current_time = int(time.time())
    if payload["exp"] <= current_time:
        return {"valid": False, "reason": "expired"}

    user_id = int(payload["sub"])
    token_type = payload["type"]

    if token_type not in ("access", "refresh"):
        return {"valid": False, "reason": "invalid_token"}

    async with AsyncSessionLocal() as db:
        # 1. Пользователь существует
        stmt = select(User.id).where(User.id == user_id)
        if (await db.execute(stmt)).scalar() is None:
            return {"valid": False, "reason": "user_not_found"}

        # 2. Сессия с этим токеном существует (не отозвана / не ротирована)
        token_hash = security.generate_token_hash(token)
        if token_type == "refresh":
            stmt = select(SessionModel.id).where(
                SessionModel.refresh_token_hash == token_hash
            )
        else:
            stmt = select(SessionModel.id).where(
                SessionModel.access_token_hash == token_hash
            )

        if (await db.execute(stmt)).scalar() is None:
            return {"valid": False, "reason": "session_not_found"}

    return {
        "valid": True,
        "type": token_type,
        "user_id": user_id,
        "space": payload["space"],
        "issued_at": payload["iat"],
        "expires_at": payload["exp"],
    }