from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.schemas.file import FileCreate, FileOut
from app.models.file import File
from app.core.subscription_guard import check_active_subscription, check_user_limits
from app.services.file_service import save_file_metadata
from sqlalchemy.future import select
import uuid
from datetime import datetime
import os

router = APIRouter()

async def get_db():
    async with async_session() as session:
        yield session

@router.post("/upload", response_model=FileOut)
async def upload_file(file_data: FileCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Save file metadata for the authenticated user."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-Id header missing")

    # Generate storage path and download link
    storage_path = save_file_metadata(file_data.original_file_name)
    direct_download_url = f"https://yourdomain.com/downloads/{uuid.uuid4().hex}"

    # Subscription and quota checks
    await check_active_subscription(user_id)
    await check_user_limits(user_id, file_data.file_size)

    new_file = File(
        id=str(uuid.uuid4()),
        user_id=user_id,
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


@router.get("/list", response_model=list[FileOut])
async def list_files(request: Request, db: AsyncSession = Depends(get_db)):
    """List all files of the authenticated user."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-Id header missing")

    result = await db.execute(select(File).where(File.user_id == user_id))
    files = result.scalars().all()
    return files


@router.delete("/delete/{file_id}")
async def delete_file(file_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Delete a file if it belongs to the authenticated user."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-Id header missing")

    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalars().first()
    if not file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if file.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    # Remove from filesystem if exists
    try:
        if os.path.exists(file.storage_path):
            os.remove(file.storage_path)
    except Exception as e:
        # Log removal failure but continue deleting DB record
        print(f"[✘] Failed to remove file {file.storage_path}: {e}")

    await db.delete(file)
    await db.commit()
    return {"detail": "File deleted"}
