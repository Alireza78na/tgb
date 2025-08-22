from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import async_session
from app.schemas.file import FileCreate, FileOut, FileLinkCreate
from app.models.file import File
from app.core.subscription_guard import (
    check_active_subscription,
    check_user_limits,
)
from app.core.user_guard import ensure_not_blocked
from app.core.auth import get_current_user
from app.core.exceptions import FileOperationError
from app.services.file_service import save_file_metadata
from app.services.download_worker import (
    download_file_from_telegram,
    get_remote_file_size,
    process_download_from_url_task,
)
from app.services.download_worker import SecurityValidator
from app.services.task_queue import task_queue, TaskConfig, TaskType
from app.core.exceptions import SecurityError
import logging
from pathlib import Path
from sqlalchemy.future import select
from sqlalchemy import func
from typing import List
import uuid
from datetime import datetime
import os
from app.core import config
from fastapi.responses import JSONResponse

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
router.state.limiter = limiter
logger = logging.getLogger(__name__)

async def get_db():
    async with async_session() as session:
        yield session


async def safe_file_deletion(file_path: str, file_id: str) -> bool:
    """Delete a file from disk with detailed logging."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Successfully deleted file: {file_id}")
            return True
        logger.warning(f"File not found for deletion: {file_id}")
        return True
    except PermissionError as e:
        logger.error(f"Permission denied deleting file {file_id}: {e}")
        raise FileOperationError("فایل قابل حذف نیست - مشکل دسترسی")
    except OSError as e:
        logger.error(f"OS error deleting file {file_id}: {e}")
        raise FileOperationError("خطا در حذف فایل از سیستم")
    except Exception as e:
        logger.error(f"Unexpected error deleting file {file_id}: {e}")
        raise FileOperationError("خطای غیرمنتظره در حذف فایل")

@router.post("/upload", response_model=FileOut)
@limiter.limit("10/minute")
async def upload_file(
    file_data: FileCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Save file metadata for the authenticated user."""
    await ensure_not_blocked(user_id)

    is_safe, reason = SecurityValidator.is_safe_filename(file_data.original_file_name)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"نوع فایل مجاز نیست: {reason}")

    # Subscription and quota checks before downloading
    await check_active_subscription(user_id, db)
    await check_user_limits(user_id, file_data.file_size, db)

    if file_data.telegram_file_id:
        result = await download_file_from_telegram(
            file_data.telegram_file_id,
            file_data.original_file_name,
        )
        if not result.success or not result.file_path:
            raise HTTPException(status_code=500, detail="Download failed")
        storage_path = result.file_path
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


@router.post("/upload_link", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def upload_from_link(
    data: FileLinkCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Accepts a URL for download and queues it as a background task."""
    is_safe_url, reason = SecurityValidator.is_safe_url(data.url)
    if not is_safe_url:
        raise HTTPException(status_code=400, detail=f"لینک غیرمجاز است: {reason}")

    file_name = data.file_name or data.url.split("/")[-1]
    is_safe_filename, reason = SecurityValidator.is_safe_filename(file_name)
    if not is_safe_filename:
        raise HTTPException(status_code=400, detail=f"نام فایل غیرمجاز است: {reason}")

    try:
        remote_size = await get_remote_file_size(data.url)
        await check_active_subscription(user_id, db)
        await check_user_limits(user_id, remote_size, db)
    except (FileOperationError, SecurityError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_config = TaskConfig(
        task_type=TaskType.FILE_DOWNLOAD,
        max_retries=1,
        timeout=3600,  # 1 hour
    )

    task_id = await task_queue.add_task(
        process_download_from_url_task,
        user_id=user_id,
        config=task_config,
        url=data.url,
        filename=file_name,
    )

    return JSONResponse(
        content={"task_id": task_id, "message": "Download task accepted"},
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get("/list", response_model=dict)
async def list_files(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search in filename"),
    file_type: str | None = Query(None, description="Filter by file extension"),
    sort_by: str | None = Query("created_at", description="Sort field"),
    sort_order: str | None = Query("desc", regex="^(asc|desc)$"),
):
    offset = (page - 1) * limit

    query = select(File).where(File.user_id == user_id)
    count_query = select(func.count(File.id)).where(File.user_id == user_id)

    if search:
        search_filter = File.original_file_name.ilike(f"%{search}%")
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if file_type:
        ext_filter = File.original_file_name.ilike(f"%.{file_type}")
        query = query.where(ext_filter)
        count_query = count_query.where(ext_filter)

    if sort_by in ["created_at", "file_size", "original_file_name"]:
        sort_column = getattr(File, sort_by)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

    query = query.offset(offset).limit(limit)

    files_result = await db.execute(query)
    count_result = await db.execute(count_query)

    files = files_result.scalars().all()
    total_count = count_result.scalar()

    return {
        "files": files,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "pages": (total_count + limit - 1) // limit,
        },
    }


@router.delete("/delete/{file_id}")
async def delete_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Delete a file if it belongs to the authenticated user."""

    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalars().first()
    if not file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if file.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    try:
        await safe_file_deletion(file.storage_path, file_id)
    except FileOperationError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    await db.delete(file)
    await db.commit()
    return {"detail": "File deleted"}


@router.post("/delete_bulk")
async def delete_bulk(
    file_ids: List[str],
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Delete multiple files of the authenticated user."""
    await ensure_not_blocked(user_id)
    result = await db.execute(select(File).where(File.id.in_(file_ids)))
    files = result.scalars().all()
    deleted = 0
    for f in files:
        if f.user_id != user_id:
            continue
        try:
            await safe_file_deletion(f.storage_path, f.id)
        except FileOperationError:
            pass
        await db.delete(f)
        deleted += 1
    await db.commit()
    return {"deleted": deleted}


@router.post("/regenerate/{file_id}", response_model=FileOut)
async def regenerate_link(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
):

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
async def download_file(
    file_id: str,
    token: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Secure file download for owner only."""
    result = await db.execute(select(File).where(File.id == file_id))
    file = result.scalars().first()
    if not file or file.download_token != token:
        raise HTTPException(status_code=404, detail="File not found")
    if file.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")

    try:
        safe_path = Path(config.UPLOAD_DIR).resolve()
        file_path = Path(file.storage_path).resolve()
        if not str(file_path).startswith(str(safe_path)):
            raise HTTPException(status_code=403, detail="Access denied")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")
    except (OSError, ValueError) as e:
        logger.error(f"Path validation error: {e}")
        raise HTTPException(status_code=500, detail="Path validation failed")

    internal_path = file_path.relative_to(safe_path)
    response = Response()
    response.headers["X-Accel-Redirect"] = f"/protected/{internal_path}"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{file.original_file_name}\""
    )
    response.headers["Content-Type"] = "application/octet-stream"
    return response
