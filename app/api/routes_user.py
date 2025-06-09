from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.schemas.user import UserCreate, UserOut
from app.models.user import User
from app.core.db import async_session

router = APIRouter()

async def get_db():
    async with async_session() as session:
        yield session

@router.post("/register", response_model=UserOut)
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.telegram_id == user.telegram_id))
    existing_user = result.scalars().first()
    if existing_user:
        return existing_user

    new_user = User(
        telegram_id=user.telegram_id,
        username=user.username,
        full_name=user.full_name
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user
