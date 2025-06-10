from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.user_guard import ensure_not_blocked
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.schemas.user import UserCreate, UserOut
from app.models.user import User
from app.models.subscription import SubscriptionPlan
from app.models.user_subscription import UserSubscription
from datetime import datetime, timedelta
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
        full_name=user.full_name,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.name == "Free")
    )
    free_plan = result.scalars().first()
    if not free_plan:
        free_plan = SubscriptionPlan(
            name="Free",
            max_storage_mb=100,
            max_files=10,
            expiry_days=3650,
            price=0,
            is_active=True,
        )
        db.add(free_plan)
        await db.commit()
        await db.refresh(free_plan)

    sub = UserSubscription(
        user_id=new_user.id,
        plan_id=free_plan.id,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=free_plan.expiry_days),
        is_active=True,
    )
    db.add(sub)
    await db.commit()

    return new_user


@router.get("/subscription")
async def get_my_subscription(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header missing")

    await ensure_not_blocked(user_id)

    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(UserSubscription.user_id == user_id, UserSubscription.is_active == True)
    )
    sub = result.scalars().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    plan = sub.plan
    return {
        "plan_name": plan.name,
        "end_date": sub.end_date,
        "is_active": sub.is_active,
    }
