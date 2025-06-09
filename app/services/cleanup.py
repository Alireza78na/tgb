import os
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.db import async_session
from app.models.file import File
from app.models.user_subscription import UserSubscription

EXPIRY_DAYS = 30

async def cleanup_expired_files():
    cutoff = datetime.utcnow() - timedelta(days=EXPIRY_DAYS)
    async with async_session() as session:
        result = await session.execute(select(File))
        files = result.scalars().all()

        deleted = 0
        for file in files:
            if file.created_at < cutoff:
                # بررسی اشتراک کاربر
                sub_result = await session.execute(
                    select(UserSubscription).where(UserSubscription.user_id == file.user_id)
                )
                sub = sub_result.scalars().first()

                if not sub or not sub.is_active or sub.end_date < datetime.utcnow():
                    try:
                        if os.path.exists(file.storage_path):
                            os.remove(file.storage_path)
                            deleted += 1
                            print(f"[✓] Deleted {file.storage_path}")
                    except Exception as e:
                        print(f"[✗] Failed to delete {file.storage_path}: {e}")

        print(f"Cleanup finished. {deleted} files deleted.")
