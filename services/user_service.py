from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.user import User
from core.exceptions import NotFoundError

class UserService:
    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int) -> User:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar()
        if not user:
            raise NotFoundError("User not found")
        return user

    # Можно добавить update_profile, get_by_username и т.д.