import asyncio
from datetime import datetime, timedelta
import requests

from sqlalchemy.future import select

from app.core.db import async_session
from app.models.user_subscription import UserSubscription
from app.models.user import User
from app.core.config import BOT_TOKEN, SUBSCRIPTION_REMINDER_DAYS


async def send_reminders():
    async with async_session() as session:
        cutoff = datetime.utcnow() + timedelta(days=SUBSCRIPTION_REMINDER_DAYS)
        result = await session.execute(
            select(UserSubscription).where(
                UserSubscription.is_active == True,
                UserSubscription.end_date <= cutoff,
                UserSubscription.reminder_sent == False,
            )
        )
        subs = result.scalars().all()
        for sub in subs:
            user_result = await session.execute(
                select(User).where(User.id == sub.user_id)
            )
            user = user_result.scalars().first()
            if not user:
                continue
            text = (
                f"اشتراک شما در تاریخ {sub.end_date.strftime('%Y-%m-%d')} به پایان می‌رسد."
            )
            try:
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data={"chat_id": user.telegram_id, "text": text},
                    timeout=10,
                )
                sub.reminder_sent = True
                await session.commit()
            except Exception as e:
                print(f"[!] Failed to send reminder to {user.telegram_id}: {e}")


if __name__ == "__main__":
    asyncio.run(send_reminders())
