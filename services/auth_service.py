import time
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from models.user import User
from models.session import Session as SessionModel
from models.schemas import RegisterRequest
from core import security
from core.snowflake import generator as snowflake_generator
from core.config import settings
from core.exceptions import ConflictError, UnauthorizedError, NotFoundError, TokenInvalidError

class AuthService:
    @staticmethod
    async def register(
        db: AsyncSession,
        data: RegisterRequest,
        client_ip: str,
        user_agent: str
    ) -> dict:
        stmt = select(User).where(User.username == data.username)
        existing = await db.execute(stmt)
        if existing.scalar():
            raise ConflictError("Username already taken")

        user_id = await snowflake_generator.generate()
        hashed = security.hash_password(data.password)

        user = User(
            id=user_id,
            username=data.username,
            display_name=data.display_name,
            password_hash=hashed,
            last_active_at=datetime.now(timezone.utc)
        )
        db.add(user)
        await db.flush()

        tokens = security.create_jwt_pair(user_id, settings.SPACE)
        session_id = await snowflake_generator.generate()
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            refresh_token_hash=tokens["refresh_hash"],
            access_token_hash=tokens["access_hash"],
            expires_at=tokens["refresh_expires_at"],
            user_agent=user_agent,
            ip_address=client_ip,
        )
        db.add(session)
        await db.commit()

        return {
            "user_id": user_id,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": tokens["expires_in"],
        }

    @staticmethod
    async def login(
        db: AsyncSession,
        username: str,
        password: str,
        client_ip: str,
        user_agent: str
    ) -> dict:
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        user = result.scalar()
        if not user or not security.verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid credentials")

        tokens = security.create_jwt_pair(user.id, settings.SPACE)
        session_id = await snowflake_generator.generate()
        session = SessionModel(
            id=session_id,
            user_id=user.id,
            refresh_token_hash=tokens["refresh_hash"],
            access_token_hash=tokens["access_hash"],
            expires_at=tokens["refresh_expires_at"],
            user_agent=user_agent,
            ip_address=client_ip,
        )
        db.add(session)
        user.last_active_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "user_id": user.id,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": tokens["expires_in"],
        }

    @staticmethod
    async def refresh(
        db: AsyncSession,
        refresh_token: str,
        client_ip: str,
        user_agent: str
    ) -> dict:
        refresh_hash = security.generate_token_hash(refresh_token)
        stmt = select(SessionModel).where(SessionModel.refresh_token_hash == refresh_hash)
        result = await db.execute(stmt)
        session = result.scalar()
        if not session:
            raise UnauthorizedError("Invalid refresh token")

        try:
            payload = security.decode_jwt(refresh_token)
        except Exception:
            raise TokenInvalidError("Invalid token format")
        if payload.get("type") != "refresh":
            raise TokenInvalidError("Not a refresh token")
        if payload.get("space") != settings.SPACE:
            raise TokenInvalidError("Space mismatch")
        if payload.get("exp", 0) <= int(time.time()):
            raise TokenInvalidError("Token expired")

        user_id = int(payload["sub"])
        new_tokens = security.create_jwt_pair(user_id, settings.SPACE)

        # Обновляем существующую сессию (id не меняется)
        session.refresh_token_hash = new_tokens["refresh_hash"]
        session.access_token_hash = new_tokens["access_hash"]
        session.expires_at = new_tokens["refresh_expires_at"]
        session.user_agent = user_agent
        session.ip_address = client_ip
        await db.commit()

        return {
            "access_token": new_tokens["access_token"],
            "refresh_token": new_tokens["refresh_token"],
            "expires_in": new_tokens["expires_in"],
        }

    @staticmethod
    async def logout(
        db: AsyncSession,
        access_token: str,
        user_id: int
    ) -> None:
        access_hash = security.generate_token_hash(access_token)
        stmt = delete(SessionModel).where(
            SessionModel.access_token_hash == access_hash,
            SessionModel.user_id == user_id
        )
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount == 0:
            raise NotFoundError("Session not found")

    @staticmethod
    async def logout_all(db: AsyncSession, user_id: int) -> None:
        stmt = delete(SessionModel).where(SessionModel.user_id == user_id)
        await db.execute(stmt)
        await db.commit()

    @staticmethod
    async def verify_token(
        db: AsyncSession,
        token: str,
        is_refresh: bool = False,
        expected_user_id: int = None
    ) -> bool:
        token_hash = security.generate_token_hash(token)
        if is_refresh:
            stmt = select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
        else:
            stmt = select(SessionModel).where(SessionModel.access_token_hash == token_hash)
        result = await db.execute(stmt)
        session = result.scalar()
        if not session:
            return False

        try:
            payload = security.decode_jwt(token)
        except Exception:
            return False

        expected_type = "refresh" if is_refresh else "access"
        if payload.get("type") != expected_type:
            return False
        if payload.get("space") != settings.SPACE:
            return False
        if payload.get("exp", 0) <= int(time.time()):
            return False
        if expected_user_id is not None and int(payload["sub"]) != expected_user_id:
            return False
        return True