from fastapi import HTTPException
from sqlalchemy.future import select
from app.core.db import async_session
from app.models.user import User

async def ensure_not_blocked(user_id: str):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user and user.is_blocked:
            raise HTTPException(status_code=403, detail="دسترسی شما مسدود شده است")
