from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.schemas.file import FileCreate, FileOut, FileLinkCreate
from app.models.file import File
from app.core.subscription_guard import (
    check_active_subscription,
    check_user_limits,
)
from app.core.user_guard import ensure_not_blocked
from app.services.file_service import save_file_metadata
from app.services.download_worker import (
    download_file_from_url,
    download_file_from_telegram,
    get_remote_file_size,
    is_blocked_extension,
    is_illegal_url,
)
from sqlalchemy.future import select
from typing import List
import uuid
from datetime import datetime
import os
from app.core import config

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

    await ensure_not_blocked(user_id)

    if is_blocked_extension(file_data.original_file_name):
        raise HTTPException(status_code=400, detail="نوع فایل مجاز نیست")

    # Subscription and quota checks before downloading
    await check_active_subscription(user_id, db)
    await check_user_limits(user_id, file_data.file_size, db)

    if file_data.telegram_file_id:
        storage_path = download_file_from_telegram(
            file_data.telegram_file_id,
            file_data.original_file_name,
        )
        if not storage_path:
            raise HTTPException(status_code=500, detail="Download failed")
    else:
        storage_path = save_file_metadata(file_data.original_file_name)

    file_id = str(uuid.uuid4())
    token = uuid.uuid4().hex
    direct_download_url = (
        f"https://{config.DOWNLOAD_DOMAIN}/api/file/download/{file_id}/{token}"
    )

    new_file = File(
        id=file_id,
        user_id=user_id,
        original_file_name=file_data.original_file_name,
        file_size=file_data.file_size,
        storage_path=storage_path,
        direct_download_url=direct_download_url,
        download_token=token,
        is_from_link=file_data.is_from_link,
        original_link=file_data.original_link,
        created_at=datetime.utcnow()
    )
    db.add(new_file)
    await db.commit()
    await db.refresh(new_file)
    return new_file


@router.post("/upload_link", response_model=FileOut)
async def upload_from_link(data: FileLinkCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Download a file from a URL and register it for the authenticated user."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-Id header missing")

    if is_illegal_url(data.url):
        raise HTTPException(status_code=400, detail="لینک غیرمجاز است")

    file_name = data.file_name or data.url.split("/")[-1]
    if is_blocked_extension(file_name):
        raise HTTPException(status_code=400, detail="نوع فایل مجاز نیست")

    remote_size = get_remote_file_size(data.url)
    await check_active_subscription(user_id, db)
    await check_user_limits(user_id, remote_size, db)

    path = download_file_from_url(data.url, file_name)
    if not path:
        raise HTTPException(status_code=500, detail="Download failed")

    file_size = os.path.getsize(path)

    file_id = str(uuid.uuid4())
    token = uuid.uuid4().hex
    direct_download_url = (
        f"https://{config.DOWNLOAD_DOMAIN}/api/file/download/{file_id}/{token}"
    )

    new_file = File(
        id=file_id,
        user_id=user_id,
        original_file_name=file_name,
        file_size=file_size,
        storage_path=path,
        direct_download_url=direct_download_url,
        download_token=token,
        is_from_link=True,
        original_link=data.url,
        created_at=datetime.utcnow(),
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


@router.post("/delete_bulk")
async def delete_bulk(file_ids: List[str], request: Request, db: AsyncSession = Depends(get_db)):
    """Delete multiple files of the authenticated user."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header missing")

    await ensure_not_blocked(user_id)
    result = await db.execute(select(File).where(File.id.in_(file_ids)))
    files = result.scalars().all()
    deleted = 0
    for f in files:
        if f.user_id != user_id:
            continue
        try:
            if os.path.exists(f.storage_path):
                os.remove(f.storage_path)
        except Exception:
            pass
        await db.delete(f)
        deleted += 1
    await db.commit()
    return {"deleted": deleted}


@router.post("/regenerate/{file_id}", response_model=FileOut)
async def regenerate_link(file_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header missing")

    await ensure_not_blocked(user_id)

    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalars().first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    if file.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")

    token = uuid.uuid4().hex
    file.direct_download_url = f"https://{config.DOWNLOAD_DOMAIN}/api/file/download/{file_id}/{token}"
    file.download_token = token
    await db.commit()
    await db.refresh(file)
    return file


@router.get("/download/{file_id}/{token}")
async def download_file(file_id: str, token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Secure file download for owner only."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header missing")
    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalars().first()
    if not file or file.download_token != token:
        raise HTTPException(status_code=404, detail="File not found")
    if file.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")

    internal_path = os.path.relpath(file.storage_path, config.UPLOAD_DIR)
    response = Response()
    response.headers["X-Accel-Redirect"] = f"/protected/{internal_path}"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{file.original_file_name}\""
    )
    return response
