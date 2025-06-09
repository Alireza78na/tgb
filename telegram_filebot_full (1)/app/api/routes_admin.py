from fastapi import APIRouter, Depends, Request
from app.core.auth import verify_admin_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.models.subscription import SubscriptionPlan
from app.models.user_subscription import UserSubscription
from app.schemas.subscription import UserSubscriptionCreate, UserSubscriptionOut
from sqlalchemy.future import select

import uuid
from datetime import datetime

router = APIRouter()

async def get_db():
    async with async_session() as session:
        yield session

@router.post("/subscription/create", response_model=UserSubscriptionOut)
async def create_subscription(
    request: Request,
    auth=Depends(verify_admin_token),data: UserSubscriptionCreate, db: AsyncSession = Depends(get_db)):
    new_subscription = UserSubscription(
        id=str(uuid.uuid4()),
        user_id=data.user_id,
        plan_id=data.plan_id,
        end_date=data.end_date,
        start_date=datetime.utcnow(),
        is_active=True
    )
    db.add(new_subscription)
    await db.commit()
    await db.refresh(new_subscription)
    return new_subscription

from app.models.file import File
from app.schemas.file import FileOut
from typing import List

@router.get("/user/{user_id}/files", response_model=List[FileOut])
async def list_user_files(
    request: Request,
    auth=Depends(verify_admin_token),user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(File).where(File.user_id == user_id))
    files = result.scalars().all()
    return files

from app.schemas.subscription import UserSubscriptionOut

@router.get("/user/{user_id}/subscription", response_model=UserSubscriptionOut)
async def get_user_subscription(
    request: Request,
    auth=Depends(verify_admin_token),user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id)
    )
    sub = result.scalars().first()
    if not sub:
        raise HTTPException(status_code=404, detail="اشتراک پیدا نشد.")
    return sub
