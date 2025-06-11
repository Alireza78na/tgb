from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

import aiohttp
import asyncio
import logging
from fastapi import Depends
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.exceptions import (
    SubscriptionExpiredError,
    SubscriptionLimitExceededError,
    DatabaseError,
)
from app.models.file import File
from app.models.subscription import SubscriptionPlan
from app.models.user import User
from app.models.user_subscription import UserSubscription

logger = logging.getLogger(__name__)


class SubscriptionGuard:
    """مدیریت امن و بهینه اشتراک‌ها"""

    def __init__(self) -> None:
        self.notification_semaphore = asyncio.Semaphore(10)

    @asynccontextmanager
    async def get_session(self, provided_session: Optional[AsyncSession] = None):
        """Context manager for database sessions."""
        if provided_session is not None:
            yield provided_session
        else:
            async with get_db() as session:
                yield session

    async def check_active_subscription(
        self,
        user_id: str,
        db: Optional[AsyncSession] = None,
        auto_create_free: bool = True,
    ) -> UserSubscription:
        """بررسی اشتراک فعال کاربر"""
        async with self.get_session(db) as session:
            try:
                query = (
                    select(UserSubscription)
                    .options(selectinload(UserSubscription.plan))
                    .where(
                        UserSubscription.user_id == user_id,
                        UserSubscription.is_active.is_(True),
                        UserSubscription.end_date > datetime.utcnow(),
                    )
                )
                result = await session.execute(query)
                active = result.scalars().first()

                if active:
                    return active

                expired_sub = await self._handle_expired_subscription(session, user_id)

                if auto_create_free:
                    free_sub = await self._create_free_subscription(session, user_id)
                    if expired_sub:
                        await self._notify_subscription_expired(user_id, session)
                    return free_sub

                raise SubscriptionExpiredError(
                    expired_sub.end_date if expired_sub else datetime.utcnow()
                )

            except Exception as e:  # pragma: no cover - logging
                logger.error("Error checking subscription for %s: %s", user_id, e)
                if isinstance(e, (SubscriptionExpiredError, SubscriptionLimitExceededError)):
                    raise
                raise DatabaseError(
                    "خطا در بررسی اشتراک",
                    details={"user_id": user_id, "error": str(e)},
                )

    async def _handle_expired_subscription(
        self, session: AsyncSession, user_id: str
    ) -> Optional[UserSubscription]:
        """Deactivate expired subscription if present."""
        expired_query = select(UserSubscription).where(
            UserSubscription.user_id == user_id,
            UserSubscription.is_active.is_(True),
            UserSubscription.end_date <= datetime.utcnow(),
        )
        result = await session.execute(expired_query)
        expired = result.scalars().first()
        if expired:
            expired.is_active = False
            expired.expired_at = datetime.utcnow()  # type: ignore[attr-defined]
            try:
                await session.commit()
                logger.info("Deactivated expired subscription for %s", user_id)
            except Exception as e:  # pragma: no cover - logging
                await session.rollback()
                logger.error("Failed to deactivate expired subscription: %s", e)
        return expired

    async def _create_free_subscription(
        self, session: AsyncSession, user_id: str
    ) -> UserSubscription:
        """Create or return a free plan subscription."""
        try:
            plan = await self._get_or_create_free_plan(session)
            new_sub = UserSubscription(
                user_id=user_id,
                plan_id=plan.id,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow() + timedelta(days=plan.expiry_days),
                is_active=True,
            )
            session.add(new_sub)
            await session.commit()
            await session.refresh(new_sub, ["plan"])
            logger.info("Created free subscription for user %s", user_id)
            return new_sub
        except IntegrityError as e:
            await session.rollback()
            logger.error("Integrity error creating free subscription: %s", e)
            result = await session.execute(
                select(UserSubscription)
                .options(selectinload(UserSubscription.plan))
                .where(UserSubscription.user_id == user_id, UserSubscription.is_active.is_(True))
            )
            existing = result.scalars().first()
            if existing:
                return existing
            raise

    async def _get_or_create_free_plan(self, session: AsyncSession) -> SubscriptionPlan:
        result = await session.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == "Free")
        )
        plan = result.scalars().first()
        if not plan:
            plan = SubscriptionPlan(
                name="Free",
                display_name="پلن رایگان",  # type: ignore[call-arg]
                max_storage_mb=100,
                max_files=10,
                expiry_days=3650,
                price=0,
                is_active=True,
            )
            session.add(plan)
            await session.flush()
            logger.info("Created new free plan")
        return plan

    async def _notify_subscription_expired(self, user_id: str, session: AsyncSession) -> None:
        async with self.notification_semaphore:
            try:
                user_res = await session.execute(select(User).where(User.id == user_id))
                user = user_res.scalars().first()
                if not user:
                    logger.warning("User %s not found for notification", user_id)
                    return
                await self._send_telegram_message(
                    user.telegram_id,
                    "🔔 اشتراک پریمیوم شما به پایان رسید و به پلن رایگان منتقل شدید.\n\n"
                    "برای ادامه استفاده از امکانات پیشرفته، اشتراک خود را تمدید کنید.",
                )
            except Exception as e:  # pragma: no cover - logging
                logger.error("Failed to notify user %s: %s", user_id, e)

    async def _send_telegram_message(self, chat_id: int, text: str) -> None:
        from app.core.config import config

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
                    data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    result: Dict[str, Any] = await response.json()
                    if not result.get("ok"):
                        error_code = result.get("error_code", 0)
                        if error_code == 403:
                            logger.warning("Bot blocked by user %s", chat_id)
                        else:
                            logger.error("Telegram API error: %s", result)
        except asyncio.TimeoutError:
            logger.warning("Timeout sending message to %s", chat_id)
        except Exception as e:  # pragma: no cover - logging
            logger.error("Error sending telegram message: %s", e)


def subscription_guard_factory() -> SubscriptionGuard:
    return SubscriptionGuard()


async def check_user_limits(
    user_id: str,
    incoming_file_size: int = 0,
    incoming_file_count: int = 1,
    db: Optional[AsyncSession] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """بررسی محدودیت‌های کاربر"""
    guard = SubscriptionGuard()
    async with guard.get_session(db) as session:
        try:
            subscription = await guard.check_active_subscription(user_id, session)
            plan = subscription.plan
            stats_query = select(
                func.coalesce(func.sum(File.file_size), 0).label("total_size"),
                func.count(File.id).label("file_count"),
            ).where(File.user_id == user_id)
            result = await session.execute(stats_query)
            stats = result.first()
            current_size = stats.total_size if stats else 0
            current_count = stats.file_count if stats else 0
            new_total_size = current_size + incoming_file_size
            new_total_count = current_count + incoming_file_count

            max_storage_bytes = (
                plan.max_storage_mb * 1024 * 1024 if plan.max_storage_mb else float("inf")
            )
            storage_exceeded = new_total_size > max_storage_bytes
            files_exceeded = plan.max_files and new_total_count > plan.max_files

            usage_info: Dict[str, Any] = {
                "current_storage_mb": round(current_size / (1024 * 1024), 2),
                "max_storage_mb": plan.max_storage_mb,
                "current_files": current_count,
                "max_files": plan.max_files,
                "storage_usage_percent": round((current_size / max_storage_bytes) * 100, 1)
                if plan.max_storage_mb
                else 0,
                "files_usage_percent": round((current_count / plan.max_files) * 100, 1)
                if plan.max_files
                else 0,
                "plan_name": plan.name,
            }

            if storage_exceeded:
                raise SubscriptionLimitExceededError(
                    "storage",
                    round(new_total_size / (1024 * 1024), 2),
                    plan.max_storage_mb,
                    details=usage_info,
                )
            if files_exceeded:
                raise SubscriptionLimitExceededError(
                    "files",
                    new_total_count,
                    plan.max_files,
                    details=usage_info,
                )
            return True, usage_info
        except Exception as e:  # pragma: no cover - logging
            logger.error("Error checking user limits for %s: %s", user_id, e)
            if isinstance(e, (SubscriptionExpiredError, SubscriptionLimitExceededError)):
                raise
            raise DatabaseError(
                "خطا در بررسی محدودیت‌های کاربر",
                details={"user_id": user_id, "error": str(e)},
            )


subscription_guard = SubscriptionGuard()


async def ensure_active_subscription(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> UserSubscription:
    """FastAPI dependency to ensure active subscription"""
    return await subscription_guard.check_active_subscription(user_id, db)


async def validate_file_upload_limits(
    user_id: str,
    file_size: int,
    db: AsyncSession = Depends(get_db),
) -> Tuple[bool, Dict[str, Any]]:
    """Dependency برای بررسی محدودیت آپلود فایل"""
    return await check_user_limits(user_id, file_size, 1, db)


async def cleanup_expired_subscriptions() -> None:
    """Background task for cleaning expired subscriptions"""
    async with get_db() as session:
        try:
            expired_query = select(UserSubscription).where(
                UserSubscription.is_active.is_(True),
                UserSubscription.end_date <= datetime.utcnow(),
            ).limit(100)
            result = await session.execute(expired_query)
            expired_list = result.scalars().all()
            if expired_list:
                for sub in expired_list:
                    sub.is_active = False
                    sub.expired_at = datetime.utcnow()  # type: ignore[attr-defined]
                await session.commit()
                logger.info("Cleaned up %d expired subscriptions", len(expired_list))
        except Exception as e:  # pragma: no cover - logging
            logger.error("Error in cleanup expired subscriptions: %s", e)
            await session.rollback()


async def get_subscription_stats(
    user_id: str, db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Retrieve usage stats for a user's subscription"""
    async with subscription_guard.get_session(db) as session:
        subscription = await subscription_guard.check_active_subscription(user_id, session)
        _, usage_info = await check_user_limits(user_id, 0, 0, session)
        days_remaining = max(0, (subscription.end_date - datetime.utcnow()).days)
        return {
            **usage_info,
            "subscription_end_date": subscription.end_date,
            "days_remaining": days_remaining,
            "subscription_active": subscription.is_active,
        }
