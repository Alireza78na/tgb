from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.user_guard import ensure_not_blocked
from app.core.auth import verify_user_token
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.schemas.user import UserCreate, UserOut
from app.schemas.subscription import UserSubscriptionDetail, SubscriptionPlanInfo
from app.models.user import User
from app.models.subscription import SubscriptionPlan
from app.models.user_subscription import UserSubscription
from app.models.file import File
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
import uuid
import logging
import time
from functools import wraps
from typing import Optional
from app.core.db import async_session

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
router.state.limiter = limiter
security = HTTPBearer()
logger = logging.getLogger(__name__)


def log_endpoint_access(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        current_user = kwargs.get("current_user")
        user_info = f"user_id={current_user.id}" if current_user else "anonymous"
        logger.info(f"Endpoint access: {func.__name__} - {user_info}")
        try:
            result = await func(*args, **kwargs)
            logger.info(
                f"Endpoint success: {func.__name__} - {round(time.time() - start_time, 3)}s"
            )
            return result
        except Exception as e:
            logger.error(
                f"Endpoint error: {func.__name__} - {e} - {round(time.time() - start_time, 3)}s"
            )
            raise

    return wrapper

async def get_db():
    async with async_session() as session:
        yield session


async def get_authenticated_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(security),
) -> User:
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = await verify_user_token(token.credentials, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    await ensure_not_blocked(user.id)
    return user


async def create_default_free_plan(db: AsyncSession) -> SubscriptionPlan:
    free_plan = SubscriptionPlan(
        id=str(uuid.uuid4()),
        name="Free",
        max_storage_mb=100,
        max_files=10,
        expiry_days=3650,
        price=0,
        is_active=True,
    )
    db.add(free_plan)
    await db.flush()
    return free_plan


async def create_free_subscription(db: AsyncSession, user_id: str):
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.name == "Free")
    )
    free_plan = result.scalars().first()
    if not free_plan:
        free_plan = await create_default_free_plan(db)

    subscription = UserSubscription(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_id=free_plan.id,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=free_plan.expiry_days),
        is_active=True,
    )
    db.add(subscription)


async def get_user_storage_stats(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(
        select(
            func.coalesce(func.sum(File.file_size), 0).label("total_size"),
            func.count(File.id).label("files_count"),
        ).where(File.user_id == user_id)
    )
    stats = result.first()
    return {
        "storage_mb": round(stats.total_size / (1024 * 1024), 2) if stats.total_size else 0,
        "files_count": stats.files_count or 0,
    }

@router.post("/register", response_model=UserOut)
@limiter.limit("3/minute")
@log_endpoint_access
async def register_user(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        async with db.begin():
            result = await db.execute(
                select(User)
                .where(User.telegram_id == user_data.telegram_id)
                .with_for_update()
            )
            existing_user = result.scalars().first()
            if existing_user:
                logger.info(f"User already exists: {user_data.telegram_id}")
                return existing_user

            new_user = User(
                id=str(uuid.uuid4()),
                telegram_id=user_data.telegram_id,
                username=user_data.username,
                full_name=user_data.full_name,
            )
            db.add(new_user)
            await db.flush()

            await create_free_subscription(db, new_user.id)

            logger.info(f"New user registered: {new_user.id}")
            return new_user
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Duplicate user registration attempt: {user_data.telegram_id}")
        result = await db.execute(select(User).where(User.telegram_id == user_data.telegram_id))
        return result.scalars().first()
    except Exception as e:
        await db.rollback()
        logger.error(f"User registration failed: {e}")
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")


@router.get("/subscription", response_model=UserSubscriptionDetail)
@limiter.limit("30/minute")
@log_endpoint_access
async def get_my_subscription(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    result = await db.execute(
        select(UserSubscription)
        .options(selectinload(UserSubscription.plan))
        .where(
            UserSubscription.user_id == current_user.id,
            UserSubscription.is_active == True,
        )
    )
    subscription = result.scalars().first()
    if not subscription:
        raise HTTPException(status_code=404, detail="هیچ اشتراک فعالی یافت نشد")

    days_remaining = max(0, (subscription.end_date - datetime.utcnow()).days)
    storage_stats = await get_user_storage_stats(db, current_user.id)

    return UserSubscriptionDetail(
        id=subscription.id,
        plan=subscription.plan,
        start_date=subscription.start_date,
        end_date=subscription.end_date,
        is_active=subscription.is_active,
        days_remaining=days_remaining,
        storage_used_mb=storage_stats["storage_mb"],
        files_count=storage_stats["files_count"],
    )
