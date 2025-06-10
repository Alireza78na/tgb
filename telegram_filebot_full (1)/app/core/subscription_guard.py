from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.models.user_subscription import UserSubscription
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from app.models.subscription import SubscriptionPlan
import requests

async def check_active_subscription(user_id: str):
    async with async_session() as session:
        result = await session.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.is_active == True)
        )
        sub = result.scalars().first()
        if not sub or sub.end_date < datetime.utcnow():
            # deactivate current subscription
            if sub:
                sub.is_active = False
                await session.commit()

            # move user to Free plan
            plan_result = await session.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.name == "Free")
            )
            free_plan = plan_result.scalars().first()
            if not free_plan:
                free_plan = SubscriptionPlan(
                    name="Free",
                    max_storage_mb=100,
                    max_files=10,
                    expiry_days=3650,
                    price=0,
                    is_active=True,
                )
                session.add(free_plan)
                await session.commit()
                await session.refresh(free_plan)

            new_sub = UserSubscription(
                user_id=user_id,
                plan_id=free_plan.id,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=free_plan.expiry_days),
                is_active=True,
            )
            session.add(new_sub)
            await session.commit()

            # inform user via Telegram
            from app.core.config import BOT_TOKEN
            from app.models.user import User
            user_res = await session.execute(select(User).where(User.id == user_id))
            usr = user_res.scalars().first()
            if usr:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                        data={
                            "chat_id": usr.telegram_id,
                            "text": "اشتراک پریمیوم شما به پایان رسید و به پلن رایگان منتقل شدید.",
                        },
                        timeout=10,
                    )
                except Exception:
                    pass

            raise HTTPException(status_code=403, detail="اشتراک شما منقضی شده است")

from app.models.file import File
from app.models.subscription import SubscriptionPlan

async def check_user_limits(user_id: str, incoming_file_size: int):
    async with async_session() as session:
        # بررسی اشتراک فعال
        result = await session.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
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
