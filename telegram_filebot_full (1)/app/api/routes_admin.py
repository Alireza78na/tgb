import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator

import aiohttp
import psutil
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.core import config as core_config
from app.core.auth import verify_admin_token
from app.core.db import async_session
from app.core.settings_manager import SettingsManager
from app.models.file import File
from app.models.subscription import SubscriptionPlan
from app.models.user import User
from app.models.user_subscription import UserSubscription
from app.schemas.file import FileOut
from app.core.config import BOT_TOKEN
from app.schemas.subscription import (
    UserSubscriptionCreate,
    UserSubscriptionOut,
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanOut,
)

logger = logging.getLogger(__name__)


class SettingsUpdate(BaseModel):
    BOT_TOKEN: Optional[str] = Field(None, min_length=10)
    DOWNLOAD_DOMAIN: Optional[str] = Field(None, regex=r"^https?://")
    UPLOAD_DIR: Optional[str] = None
    SUBSCRIPTION_REMINDER_DAYS: Optional[int] = Field(None, ge=1, le=30)
    ADMIN_IDS: Optional[str] = None
    REQUIRED_CHANNEL: Optional[str] = None

    @validator("ADMIN_IDS")
    def validate_admin_ids(cls, v):
        if v:
            try:
                ids = [int(uid) for uid in v.split(",") if uid.strip()]
                return ",".join(map(str, ids))
            except ValueError:
                raise ValueError("Invalid admin IDs format")
        return v

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
router.state.limiter = limiter
templates = Jinja2Templates(directory="app/templates")

async def get_db():
    async with async_session() as session:
        yield session


@router.post("/plan", response_model=SubscriptionPlanOut)
async def create_plan(
    data: SubscriptionPlanCreate,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    try:
        plan = SubscriptionPlan(id=str(uuid.uuid4()), **data.dict())
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
        return plan
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A plan with this name already exists.")
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create plan: {e}")
        raise HTTPException(status_code=500, detail="Failed to create plan")


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

@router.get("/user/{user_id}/files", response_model=List[FileOut])
async def list_user_files(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token)):
    result = await db.execute(select(File).where(File.user_id == user_id))
    files = result.scalars().all()
    return files

@router.get("/user/{user_id}/subscription", response_model=UserSubscriptionOut)
async def get_user_subscription(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token)):
    # Verify that the user exists before checking subscription
    user_result = await db.execute(select(User).where(User.id == user_id))
    if not user_result.scalars().first():
        raise HTTPException(status_code=404, detail="کاربر یافت نشد")

    result = await db.execute(
        select(UserSubscription).where(UserSubscription.user_id == user_id)
    )
    sub = result.scalars().first()
    if not sub:
        raise HTTPException(status_code=404, detail="اشتراک فعالی برای این کاربر یافت نشد")
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
    q: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    offset = (page - 1) * limit
    query = select(User)
    if q:
        like = f"%{q}%"
        query = query.where((User.username.ilike(like)) | (User.full_name.ilike(like)))

    total_query = select(func.count(User.id))
    if q:
        total_query = total_query.where((User.username.ilike(like)) | (User.full_name.ilike(like)))
    total_result = await db.execute(total_query)
    total = total_result.scalar()

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "users": users,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/files")
async def list_all_files(
    q: str | None = Query(None, max_length=100),
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
    except OSError as e:
        logger.error(f"Failed to delete file {file.storage_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during file deletion: {e}")
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


@router.post("/broadcast")
@limiter.limit("1/minute")
async def broadcast(
    message: str,
    db: AsyncSession = Depends(get_db),
    auth: None = Depends(verify_admin_token),
):
    result = await db.execute(select(User.telegram_id))
    ids = [row[0] for row in result.all()]

    async def send_message(session: aiohttp.ClientSession, chat_id: int):
        try:
            async with session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": chat_id, "text": message},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                return await response.json()
        except Exception as e:
            logger.warning(f"Failed to send message to {chat_id}: {e}")
            return None

    async with aiohttp.ClientSession() as session:
        tasks = [send_message(session, tid) for tid in ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    successful = sum(
        1 for r in results if r and isinstance(r, dict) and r.get("ok")
    )
    return {"sent": successful, "total": len(ids)}


@router.get("/metrics")
async def get_metrics(auth: None = Depends(verify_admin_token)):
    data = {
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "net_sent": psutil.net_io_counters().bytes_sent,
        "net_recv": psutil.net_io_counters().bytes_recv,
    }
    return JSONResponse(data)


@router.get("/panel", response_class=HTMLResponse)
async def admin_panel(request: Request, auth: None = Depends(verify_admin_token)):
    settings = SettingsManager.load()
    return templates.TemplateResponse("panel.html", {"request": request, "settings": settings})


@router.post("/settings")
async def update_settings(
    data: SettingsUpdate,
    auth: None = Depends(verify_admin_token),
):
    updated = SettingsManager.update(data.dict(exclude_unset=True))
    core_config.BOT_TOKEN = updated.get("BOT_TOKEN", core_config.BOT_TOKEN)
    core_config.DOWNLOAD_DOMAIN = updated.get("DOWNLOAD_DOMAIN", core_config.DOWNLOAD_DOMAIN)
    core_config.UPLOAD_DIR = updated.get("UPLOAD_DIR", core_config.UPLOAD_DIR)
    core_config.SUBSCRIPTION_REMINDER_DAYS = int(
        updated.get("SUBSCRIPTION_REMINDER_DAYS", core_config.SUBSCRIPTION_REMINDER_DAYS)
    )
    core_config.ADMIN_IDS = {
        int(uid)
        for uid in str(updated.get("ADMIN_IDS", "")).split(",")
        if uid
    }
    core_config.REQUIRED_CHANNEL = updated.get(
        "REQUIRED_CHANNEL", core_config.REQUIRED_CHANNEL
    )
    return {"detail": "updated", "settings": updated}
