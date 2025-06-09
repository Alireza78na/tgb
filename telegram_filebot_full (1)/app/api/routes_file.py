from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.schemas.file import FileCreate, FileOut
from app.models.file import File
from app.core.subscription_guard import check_active_subscription, check_user_limits
from app.services.file_service import save_file_metadata
from sqlalchemy.future import select
import uuid
from datetime import datetime

router = APIRouter()

async def get_db():
    async with async_session() as session:
        yield session

@router.post("/upload", response_model=FileOut)
async def upload_file(file_data: FileCreate, request: Request, db: AsyncSession = Depends(get_db)):
    # ساخت مسیر فایل
    storage_path = save_file_metadata(file_data.original_file_name)
    direct_download_url = f"https://yourdomain.com/downloads/{uuid.uuid4().hex}"

    await check_active_subscription(update.message.from_user.id  # real Telegram user_id)
    await check_user_limits(update.message.from_user.id  # real Telegram user_id, file_data.file_size)  # جایگزین با user_id واقعی در اتصال با ربات

    new_file = File(
        id=str(uuid.uuid4()),
        user_id="mock-user-id",  # برای تست فعلاً مقدار ثابت
        original_file_name=file_data.original_file_name,
        file_size=file_data.file_size,
        storage_path=storage_path,
        direct_download_url=direct_download_url,
        is_from_link=file_data.is_from_link,
        original_link=file_data.original_link,
        created_at=datetime.utcnow()
    )
    db.add(new_file)
    await db.commit()
    await db.refresh(new_file)
    return new_file
