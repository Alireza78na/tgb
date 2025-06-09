from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.models.user_subscription import UserSubscription
from sqlalchemy.future import select
from datetime import datetime

async def check_active_subscription(user_id: str):
    async with async_session() as session:
        result = await session.execute(
            select(UserSubscription)
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.is_active == True)
        )
        sub = result.scalars().first()
        if not sub or sub.end_date < datetime.utcnow():
            raise HTTPException(status_code=403, detail="اشتراک شما منقضی شده یا فعال نیست.")

from app.models.file import File
from app.models.subscription import SubscriptionPlan

async def check_user_limits(user_id: str, incoming_file_size: int):
    async with async_session() as session:
        # بررسی اشتراک فعال
        result = await session.execute(
            select(UserSubscription)
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.is_active == True)
        )
        sub = result.scalars().first()
        if not sub or sub.end_date < datetime.utcnow():
            raise HTTPException(status_code=403, detail="اشتراک شما منقضی شده یا فعال نیست.")

        # دریافت پلن مربوطه
        plan = sub.plan

        # مجموع حجم فایل‌های آپلودشده
        result = await session.execute(
            select(File).where(File.user_id == user_id)
        )
        files = result.scalars().all()
        total_size = sum(f.file_size for f in files)
        total_count = len(files)

        if plan and (
            (plan.max_storage_mb and (total_size + incoming_file_size) > plan.max_storage_mb * 1024 * 1024) or
            (plan.max_files and total_count >= plan.max_files)
        ):
            raise HTTPException(status_code=403, detail="شما به محدودیت حجم یا تعداد فایل رسیده‌اید.")
