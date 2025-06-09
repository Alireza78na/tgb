from fastapi import APIRouter, Depends, Request, HTTPException
import requests
import os
from app.core.auth import verify_admin_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.models.user import User
from app.models.subscription import SubscriptionPlan
from app.models.user_subscription import UserSubscription
from app.schemas.subscription import (
    UserSubscriptionCreate,
    UserSubscriptionOut,
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanOut,
)
from sqlalchemy.future import select
from typing import List

import uuid
from datetime import datetime

router = APIRouter()

async def get_db():
    async with async_session() as session:
        yield session


@router.post("/plan", response_model=SubscriptionPlanOut)
async def create_plan(
    data: SubscriptionPlanCreate,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    plan = SubscriptionPlan(id=str(uuid.uuid4()), **data.dict())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/plan/{plan_id}", response_model=SubscriptionPlanOut)
async def update_plan(
    plan_id: str,
    data: SubscriptionPlanUpdate,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    for key, value in data.dict(exclude_unset=True).items():
        setattr(plan, key, value)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/plan", response_model=List[SubscriptionPlanOut])
async def list_plans(
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(SubscriptionPlan))
    plans = result.scalars().all()
    return plans


@router.get("/plan/{plan_id}", response_model=SubscriptionPlanOut)
async def get_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.delete("/plan/{plan_id}")
async def delete_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    await db.delete(plan)
    await db.commit()
    return {"detail": "deleted"}

@router.post("/subscription/create", response_model=UserSubscriptionOut)
async def create_subscription(
    request: Request,
    data: UserSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token)):
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

@router.get("/user/{user_id}/files", response_model=List[FileOut])
async def list_user_files(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token)):
    result = await db.execute(select(File).where(File.user_id == user_id))
    files = result.scalars().all()
    return files

from app.schemas.subscription import UserSubscriptionOut

@router.get("/user/{user_id}/subscription", response_model=UserSubscriptionOut)
async def get_user_subscription(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token)):
    result = await db.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id)
    )
    sub = result.scalars().first()
    if not sub:
        raise HTTPException(status_code=404, detail="اشتراک پیدا نشد.")
    return sub


@router.post("/user/block/{user_id}")
async def block_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    user.is_blocked = True
    await db.commit()
    return {"detail": "blocked"}


@router.post("/user/unblock/{user_id}")
async def unblock_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")
    user.is_blocked = False
    await db.commit()
    return {"detail": "unblocked"}


@router.get("/users")
async def list_users(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    query = select(User)
    if q:
        like = f"%{q}%"
        query = query.where((User.username.ilike(like)) | (User.full_name.ilike(like)))
    result = await db.execute(query)
    users = result.scalars().all()
    return users


@router.get("/files")
async def list_all_files(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    query = select(File)
    if q:
        like = f"%{q}%"
        query = query.where(File.original_file_name.ilike(like))
    result = await db.execute(query)
    files = result.scalars().all()
    return files


@router.delete("/file/{file_id}")
async def admin_delete_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalars().first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        if os.path.exists(file.storage_path):
            os.remove(file.storage_path)
    except Exception:
        pass
    await db.delete(file)
    await db.commit()
    return {"detail": "deleted"}


@router.post("/subscription/cancel/{user_id}")
async def cancel_subscription(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id, UserSubscription.is_active == True)
    )
    sub = result.scalars().first()
    if not sub:
        raise HTTPException(status_code=404, detail="اشتراک فعال یافت نشد")
    sub.is_active = False
    await db.commit()
    return {"detail": "subscription cancelled"}


from app.core.config import BOT_TOKEN


@router.post("/broadcast")
async def broadcast(message: str, db: AsyncSession = Depends(get_db), auth: None = Depends(verify_admin_token)):
    result = await db.execute(select(User.telegram_id))
    ids = [row[0] for row in result.all()]
    for tid in ids:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": tid, "text": message},
                timeout=10,
            )
        except Exception:
            pass
    return {"sent": len(ids)}
