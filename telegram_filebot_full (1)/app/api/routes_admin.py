from fastapi import APIRouter, Depends, Request, HTTPException
from app.core.auth import verify_admin_token
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
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
