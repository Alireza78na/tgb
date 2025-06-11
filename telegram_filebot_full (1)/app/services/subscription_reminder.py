import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.db import get_db
from app.models.subscription import SubscriptionPlan
from app.models.user import User, UserStatus
from app.models.user_subscription import SubscriptionStatus, UserSubscription


logger = logging.getLogger(__name__)
config = get_config()


class ReminderType(Enum):
    """Possible reminder types."""

    EXPIRY_WARNING = "expiry_warning"
    EXPIRY_URGENT = "expiry_urgent"
    EXPIRED = "expired"
    RENEWAL_AVAILABLE = "renewal_available"
    UPGRADE_OFFER = "upgrade_offer"


class MessageTemplate(Enum):
    """Supported message templates."""

    WARNING_7_DAYS = "warning_7_days"
    WARNING_3_DAYS = "warning_3_days"
    WARNING_1_DAY = "warning_1_day"
    EXPIRED_TODAY = "expired_today"
    EXPIRED_GRACE = "expired_grace"
    RENEWAL_OFFER = "renewal_offer"


@dataclass
class ReminderResult:
    """Result of sending a reminder."""

    user_id: str
    telegram_id: int
    success: bool
    error: Optional[str] = None
    message_type: Optional[ReminderType] = None


@dataclass
class ReminderStats:
    """Aggregated statistics for reminders."""

    total_checked: int = 0
    reminders_sent: int = 0
    errors: int = 0
    skipped: int = 0
    by_type: Dict[ReminderType, int] | None = None
    execution_time: float = 0.0

    def __post_init__(self) -> None:  # pragma: no cover - simple default init
        if self.by_type is None:
            self.by_type = {}


class MessageLocalizer:
    """Localized message templates."""

    MESSAGES = {
        "fa": {
            MessageTemplate.WARNING_7_DAYS: (
                """
🔔 **یادآوری اشتراک**

سلام {name},

اشتراک {plan_name} شما در **{days_remaining} روز** ({end_date}) به پایان می‌رسد.

📊 **وضعیت فعلی:**
• حجم استفاده شده: {storage_used_mb} MB از {storage_limit_mb} MB
• فایل‌های شما: {files_count} از {files_limit}

💡 برای تمدید اشتراک از دستور /renew استفاده کنید.

🔗 [مشاهده پلن‌های جدید](/plans)
                """
            ),
            MessageTemplate.WARNING_3_DAYS: (
                """
⚠️ **هشدار مهم - اشتراک**

{name} عزیز,

اشتراک شما تنها **{days_remaining} روز** دیگر اعتبار دارد!

⏰ تاریخ انقضا: {end_date}
📦 پلن فعلی: {plan_name}

🚨 **توجه:** پس از انقضا، دسترسی به فایل‌هایتان محدود خواهد شد.

🔄 **تمدید فوری:** /renew_{plan_id}
📈 **ارتقا پلن:** /upgrade
                """
            ),
            MessageTemplate.WARNING_1_DAY: (
                """
🚨 **هشدار فوری**

{name}، اشتراک شما **فردا** منقضی می‌شود!

⏰ پایان اشتراک: {end_date}
⚡ برای جلوگیری از قطع سرویس، همین الان تمدید کنید.

🔄 تمدید سریع: /renew
💳 پرداخت آنلاین: /payment
📞 پشتیبانی: /support
                """
            ),
            MessageTemplate.EXPIRED_TODAY: (
                """
❌ **اشتراک منقضی شد**

{name}، اشتراک {plan_name} شما امروز به پایان رسید.

📝 **وضعیت جدید:**
• انتقال به پلن رایگان
• دسترسی محدود به فایل‌ها
• حداکثر {free_storage_mb} MB فضای ذخیره‌سازی

🔄 **بازگشت به پلن قبلی:** /reactivate
📋 **مشاهده پلن‌های جدید:** /plans
                """
            ),
            MessageTemplate.RENEWAL_OFFER: (
                """
🎯 **پیشنهاد ویژه تمدید**

{name}، فرصت بازگشت به {plan_name} را از دست ندهید!

🎁 **تخفیف ویژه:** {discount_percent}% تا {offer_expires}

💰 قیمت با تخفیف: {discounted_price} {currency}
⭐ تمام امکانات پلن قبلی

🛒 **سفارش با تخفیف:** /renew_discount_{code}
                """
            ),
        }
    }

    @classmethod
    def get_message(
        cls, template: MessageTemplate, language: str, **kwargs: Any
    ) -> str:
        templates = cls.MESSAGES.get(language, cls.MESSAGES["fa"])
        msg_template = templates.get(template, templates[MessageTemplate.WARNING_7_DAYS])
        try:
            return msg_template.format(**kwargs)
        except KeyError as exc:  # pragma: no cover - fail safe
            logger.warning("Missing template variable: %s", exc)
            return msg_template


class TelegramNotificationService:
    """Wrapper around Telegram sendMessage API with basic rate limiting."""

    def __init__(self) -> None:
        self.bot_token = config.BOT_TOKEN
        self.session: aiohttp.ClientSession | None = None
        self.rate_limiter = asyncio.Semaphore(20)

    @asynccontextmanager
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        try:
            yield self.session
        finally:
            pass

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional[Dict[str, Any]] = None,
        retry_count: int = 3,
    ) -> Tuple[bool, Optional[str]]:
        async with self.rate_limiter:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            data: Dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
            if reply_markup:
                data["reply_markup"] = json.dumps(reply_markup)

            for attempt in range(retry_count):
                try:
                    async with self.get_session() as session:
                        async with session.post(url, data=data) as resp:
                            result = await resp.json()
                            if result.get("ok"):
                                return True, None
                            error_code = result.get("error_code", 0)
                            desc = result.get("description", "Unknown error")
                            if error_code in {429, 502, 503, 504} and attempt < retry_count - 1:
                                await asyncio.sleep(2**attempt)
                                continue
                            if error_code == 403:
                                return False, "User blocked the bot"
                            if error_code == 400:
                                return False, f"Bad request: {desc}"
                            return False, f"API Error {error_code}: {desc}"
                except asyncio.TimeoutError:
                    if attempt < retry_count - 1:
                        await asyncio.sleep(1)
                        continue
                    return False, "Request timeout"
                except Exception as exc:  # pragma: no cover - network errors
                    if attempt < retry_count - 1:
                        await asyncio.sleep(1)
                        continue
                    return False, f"Network error: {exc}"
        return False, "Max retries exceeded"

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None


class AdvancedSubscriptionReminderService:
    """Service for sending subscription reminders."""

    def __init__(self) -> None:
        self.config = get_config()
        self.notification_service = TelegramNotificationService()
        self.reminder_days = [7, 3, 1, 0]

    async def send_subscription_reminders(
        self, custom_reminder_days: Optional[List[int]] = None, batch_size: int = 50
    ) -> ReminderStats:
        start_time = datetime.utcnow()
        stats = ReminderStats()
        reminder_days = custom_reminder_days or self.reminder_days

        try:
            async with get_db() as session:
                for days_ahead in reminder_days:
                    batch_stats = await self._process_reminder_batch(session, days_ahead, batch_size)
                    self._merge_stats(stats, batch_stats)

                renewal_stats = await self._send_renewal_offers(session, batch_size)
                self._merge_stats(stats, renewal_stats)

            stats.execution_time = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                "Reminder service completed: Sent=%s Errors=%s Time=%.2fs",
                stats.reminders_sent,
                stats.errors,
                stats.execution_time,
            )
            return stats
        except Exception as exc:  # pragma: no cover - log errors
            logger.error("Reminder service failed: %s", exc, exc_info=True)
            stats.errors += 1
            return stats
        finally:
            await self.notification_service.close()

    async def _process_reminder_batch(
        self, session: AsyncSession, days_ahead: int, batch_size: int
    ) -> ReminderStats:
        stats = ReminderStats()

        if days_ahead == 0:
            target_date_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            target_date_end = target_date_start + timedelta(days=1)
        else:
            target_date_start = datetime.utcnow() + timedelta(days=days_ahead)
            target_date_end = target_date_start + timedelta(days=1)

        query = (
            select(UserSubscription, User, SubscriptionPlan)
            .join(User, UserSubscription.user_id == User.id)
            .join(SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id)
            .where(
                and_(
                    UserSubscription.status == SubscriptionStatus.ACTIVE,
                    UserSubscription.end_date >= target_date_start,
                    UserSubscription.end_date < target_date_end,
                    User.status == UserStatus.ACTIVE,
                    User.deleted_at.is_(None),
                )
            )
        )

        if days_ahead > 0:
            query = query.where(
                or_(UserSubscription.reminder_sent.is_(None), UserSubscription.reminder_sent == False)
            )

        offset = 0
        while True:
            batch_query = query.offset(offset).limit(batch_size)
            result = await session.execute(batch_query)
            batch = result.all()
            if not batch:
                break

            stats.total_checked += len(batch)

            tasks = [self._send_single_reminder(sub, usr, plan, days_ahead) for sub, usr, plan in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            successful_subs: List[str] = []
            for i, result in enumerate(results):
                subscription = batch[i][0]
                if isinstance(result, ReminderResult):
                    if result.success:
                        stats.reminders_sent += 1
                        successful_subs.append(subscription.id)
                        rtype = result.message_type or ReminderType.EXPIRY_WARNING
                        stats.by_type[rtype] = stats.by_type.get(rtype, 0) + 1
                    else:
                        stats.errors += 1
                        logger.warning("Failed to send reminder to %s: %s", result.user_id, result.error)
                else:
                    stats.errors += 1
                    logger.error("Exception in reminder task: %s", result)

            if successful_subs and days_ahead > 0:
                await session.execute(
                    update(UserSubscription)
                    .where(UserSubscription.id.in_(successful_subs))
                    .values(reminder_sent=True, reminder_sent_at=datetime.utcnow())
                )
                await session.commit()

            offset += len(batch)
            if offset > 5000:  # safety limit
                logger.warning("Reached maximum reminder limit per run")
                break

        return stats

    async def _send_single_reminder(
        self, subscription: UserSubscription, user: User, plan: SubscriptionPlan, days_ahead: int
    ) -> ReminderResult:
        try:
            if days_ahead == 7:
                template = MessageTemplate.WARNING_7_DAYS
                rtype = ReminderType.EXPIRY_WARNING
            elif days_ahead == 3:
                template = MessageTemplate.WARNING_3_DAYS
                rtype = ReminderType.EXPIRY_WARNING
            elif days_ahead == 1:
                template = MessageTemplate.WARNING_1_DAY
                rtype = ReminderType.EXPIRY_URGENT
            elif days_ahead == 0:
                template = MessageTemplate.EXPIRED_TODAY
                rtype = ReminderType.EXPIRED
            else:
                template = MessageTemplate.WARNING_7_DAYS
                rtype = ReminderType.EXPIRY_WARNING

            usage_stats = await self._get_user_usage_stats(subscription.user_id)

            template_vars = {
                "name": user.first_name or "کاربر",
                "plan_name": plan.display_name or plan.name,
                "days_remaining": max(0, (subscription.end_date - datetime.utcnow()).days),
                "end_date": subscription.end_date.strftime("%Y/%m/%d"),
                "storage_used_mb": usage_stats.get("storage_used_mb", 0),
                "storage_limit_mb": plan.max_storage_mb,
                "files_count": usage_stats.get("files_count", 0),
                "files_limit": plan.max_files,
                "plan_id": plan.id,
                "free_storage_mb": 100,
            }

            message = MessageLocalizer.get_message(
                template, user.language_code.value if user.language_code else "fa", **template_vars
            )

            reply_markup = self._create_reminder_keyboard(subscription, plan, days_ahead)

            success, error = await self.notification_service.send_message(
                user.telegram_id, message, reply_markup=reply_markup
            )

            return ReminderResult(
                user_id=user.id,
                telegram_id=user.telegram_id,
                success=success,
                error=error,
                message_type=rtype,
            )
        except Exception as exc:  # pragma: no cover - log errors
            logger.error("Error sending reminder to user %s: %s", user.id, exc)
            return ReminderResult(user_id=user.id, telegram_id=user.telegram_id, success=False, error=str(exc))

    def _create_reminder_keyboard(
        self, subscription: UserSubscription, plan: SubscriptionPlan, days_ahead: int
    ) -> Dict[str, Any]:
        buttons: List[List[Dict[str, Any]]] = []
        if days_ahead > 0:
            buttons.append(
                [
                    {"text": "🔄 تمدید همین پلن", "callback_data": f"renew_{subscription.id}"},
                    {"text": "📈 ارتقا پلن", "callback_data": f"upgrade_{subscription.id}"},
                ]
            )
            buttons.append(
                [
                    {"text": "💳 پرداخت آنلاین", "callback_data": f"payment_{subscription.id}"},
                    {"text": "📞 پشتیبانی", "callback_data": "support"},
                ]
            )
        else:
            buttons.append(
                [
                    {"text": "🔄 بازفعال‌سازی", "callback_data": f"reactivate_{subscription.id}"},
                    {"text": "📋 پلن‌های جدید", "callback_data": "plans"},
                ]
            )
        return {"inline_keyboard": buttons}

    async def _get_user_usage_stats(self, user_id: str) -> Dict[str, Any]:
        try:
            async with get_db() as session:
                from app.models.file import File

                result = await session.execute(
                    select(
                        func.count(File.id).label("files_count"),
                        func.coalesce(func.sum(File.file_size), 0).label("total_size"),
                    ).where(and_(File.user_id == user_id, File.deleted_at.is_(None)))
                )
                stats = result.first()
                return {
                    "files_count": stats.files_count or 0,
                    "storage_used_mb": round((stats.total_size or 0) / (1024 * 1024), 2),
                }
        except Exception as exc:  # pragma: no cover - log errors
            logger.error("Error getting user usage stats: %s", exc)
            return {"files_count": 0, "storage_used_mb": 0}

    async def _send_renewal_offers(self, session: AsyncSession, batch_size: int) -> ReminderStats:
        stats = ReminderStats()

        cutoff_start = datetime.utcnow() - timedelta(days=7)
        cutoff_end = datetime.utcnow() - timedelta(days=1)

        query = (
            select(UserSubscription, User, SubscriptionPlan)
            .join(User, UserSubscription.user_id == User.id)
            .join(SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id)
            .where(
                and_(
                    UserSubscription.status == SubscriptionStatus.EXPIRED,
                    UserSubscription.end_date >= cutoff_start,
                    UserSubscription.end_date <= cutoff_end,
                    User.status == UserStatus.ACTIVE,
                    UserSubscription.renewal_notification_sent == False,
                )
            )
            .limit(batch_size)
        )

        result = await session.execute(query)
        expired_subs = result.all()

        for subscription, user, plan in expired_subs:
            try:
                message = MessageLocalizer.get_message(
                    MessageTemplate.RENEWAL_OFFER,
                    user.language_code.value if user.language_code else "fa",
                    name=user.first_name or "کاربر",
                    plan_name=plan.display_name or plan.name,
                    discount_percent=20,
                    offer_expires="۱۰ روز آینده",
                    discounted_price=int(plan.price * 0.8),
                    currency="تومان",
                    code="RETURN20",
                )

                success, error = await self.notification_service.send_message(user.telegram_id, message)

                if success:
                    subscription.renewal_notification_sent = True
                    stats.reminders_sent += 1
                else:
                    stats.errors += 1
                    logger.warning("Failed to send renewal offer to %s: %s", user.id, error)
            except Exception as exc:  # pragma: no cover - log errors
                logger.error("Error sending renewal offer to %s: %s", user.id, exc)
                stats.errors += 1

        await session.commit()
        return stats

    def _merge_stats(self, main_stats: ReminderStats, batch_stats: ReminderStats) -> None:
        main_stats.total_checked += batch_stats.total_checked
        main_stats.reminders_sent += batch_stats.reminders_sent
        main_stats.errors += batch_stats.errors
        main_stats.skipped += batch_stats.skipped
        for rtype, count in batch_stats.by_type.items():
            main_stats.by_type[rtype] = main_stats.by_type.get(rtype, 0) + count


reminder_service = AdvancedSubscriptionReminderService()


async def send_subscription_reminders(custom_reminder_days: Optional[List[int]] = None) -> ReminderStats:
    return await reminder_service.send_subscription_reminders(custom_reminder_days)


async def send_single_user_reminder(user_id: str) -> bool:
    try:
        async with get_db() as session:
            result = await session.execute(
                select(UserSubscription, User, SubscriptionPlan)
                .join(User, UserSubscription.user_id == User.id)
                .join(SubscriptionPlan, UserSubscription.plan_id == SubscriptionPlan.id)
                .where(
                    and_(UserSubscription.user_id == user_id, UserSubscription.status == SubscriptionStatus.ACTIVE)
                )
            )
            row = result.first()
            if not row:
                return False
            subscription, user, plan = row
            days_remaining = (subscription.end_date - datetime.utcnow()).days
            reminder_result = await reminder_service._send_single_reminder(subscription, user, plan, days_remaining)
            return reminder_result.success
    except Exception as exc:  # pragma: no cover - log errors
        logger.error("Error sending single user reminder: %s", exc)
        return False


async def scheduled_reminder_task() -> ReminderStats:
    try:
        stats = await send_subscription_reminders()
        if stats.errors > 0:
            await send_reminder_report_to_admins(stats)
        return stats
    except Exception as exc:  # pragma: no cover - log errors
        logger.error("Scheduled reminder task failed: %s", exc, exc_info=True)
        raise


async def send_reminder_report_to_admins(stats: ReminderStats) -> None:
    try:
        message = (
            f"""
📊 **گزارش یادآوری اشتراک**

✅ یادآوری‌های ارسال شده: {stats.reminders_sent}
❌ خطاها: {stats.errors}
📋 کل بررسی شده: {stats.total_checked}
⏱ زمان اجرا: {stats.execution_time:.2f} ثانیه

**تفکیک نوع:**
"""
            + "\n".join([f"• {t.value}: {c}" for t, c in stats.by_type.items()])
        )
        # Implementation for sending admin notifications should be added here.
        # await send_admin_notification(message)
    except Exception as exc:  # pragma: no cover - log errors
        logger.error("Failed to send reminder report: %s", exc)


if __name__ == "__main__":
    asyncio.run(send_subscription_reminders())

