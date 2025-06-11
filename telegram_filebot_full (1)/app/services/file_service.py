import asyncio
import hashlib
import json
import logging
import re
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import aiofiles
import magic
from PIL import Image
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import config as app_config
from app.core.exceptions import FileOperationError, ValidationError
from app.models.file import File, FileStatus, FileType

logger = logging.getLogger(__name__)


class FileOperation(Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE = "delete"
    MOVE = "move"
    COPY = "copy"
    COMPRESS = "compress"
    EXTRACT = "extract"


class StorageType(Enum):
    LOCAL = "local"
    S3 = "s3"
    MINIO = "minio"
    FTP = "ftp"


class CompressionType(Enum):
    NONE = "none"
    GZIP = "gzip"
    ZIP = "zip"
    RAR = "rar"


class FileValidator:
    BLOCKED_EXTENSIONS = set(app_config.BLOCKED_EXTENSIONS)

    @classmethod
    def validate_filename(cls, filename: str) -> Tuple[bool, str]:
        if not filename or len(filename.strip()) == 0:
            return False, "نام فایل نمی‌تواند خالی باشد"
        filename = filename.strip()
        if len(filename) > 255:
            return False, "نام فایل بیش از 255 کاراکتر نمی‌تواند باشد"
        dangerous_chars = ["/", "\\", "..", "<", ">", ":", '"', "|", "?", "*", "\0", "\r", "\n"]
        for char in dangerous_chars:
            if char in filename:
                return False, f"نام فایل نمی‌تواند شامل '{char}' باشد"
        if "." not in filename:
            return False, "نام فایل باید دارای پسوند باشد"
        extension = Path(filename).suffix.lower()
        if extension in cls.BLOCKED_EXTENSIONS:
            return False, f"نوع فایل '{extension}' مجاز نیست"
        reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "LPT1", "LPT2"}
        name_no_ext = Path(filename).stem.upper()
        if name_no_ext in reserved:
            return False, f"نام '{name_no_ext}' محفوظ شده است"
        return True, "ok"

    @staticmethod
    def detect_file_type(file_path: Path) -> Tuple[FileType, str]:
        try:
            mime_type = magic.from_file(str(file_path), mime=True)
            if mime_type.startswith("image/"):
                return FileType.IMAGE, mime_type
            if mime_type.startswith("video/"):
                return FileType.VIDEO, mime_type
            if mime_type.startswith("audio/"):
                return FileType.AUDIO, mime_type
            if mime_type in ["application/pdf", "text/plain"] or mime_type.startswith("application/vnd."):
                return FileType.DOCUMENT, mime_type
            if mime_type.startswith("application/") and any(x in mime_type for x in ["zip", "rar", "7z", "tar"]):
                return FileType.ARCHIVE, mime_type
            return FileType.OTHER, mime_type
        except Exception as e:  # pragma: no cover - best effort fallback
            logger.warning("Failed to detect MIME type for %s: %s", file_path, e)
            ext = file_path.suffix.lower()
            if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                return FileType.IMAGE, "image/unknown"
            if ext in {".mp4", ".avi", ".mkv", ".mov"}:
                return FileType.VIDEO, "video/unknown"
            if ext in {".mp3", ".wav", ".flac", ".ogg"}:
                return FileType.AUDIO, "audio/unknown"
            return FileType.OTHER, "application/octet-stream"


class FileHashManager:
    @staticmethod
    async def calculate_file_hashes(file_path: Path, chunk_size: int = 8192) -> Dict[str, str]:
        md5_hash = hashlib.md5()
        sha256_hash = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
        return {"md5": md5_hash.hexdigest(), "sha256": sha256_hash.hexdigest()}

    @staticmethod
    async def find_duplicate_files(session: AsyncSession, file_hash: str) -> List[File]:
        result = await session.execute(
            select(File).where(
                and_(File.file_hash_md5 == file_hash, File.deleted_at.is_(None), File.status == FileStatus.READY)
            )
        )
        return result.scalars().all()


class FileMetadataExtractor:
    @staticmethod
    async def extract_image_metadata(file_path: Path) -> Dict[str, Any]:
        try:
            def _extract() -> Dict[str, Any]:
                with Image.open(file_path) as img:
                    data = {"width": img.width, "height": img.height, "format": img.format, "mode": img.mode}
                    if hasattr(img, "_getexif") and img._getexif():
                        data["exif"] = dict(img._getexif())
                    return data
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _extract)
        except Exception as e:
            logger.warning("Failed to extract image metadata: %s", e)
            return {}

    @staticmethod
    async def extract_video_metadata(file_path: Path) -> Dict[str, Any]:
        try:
            import subprocess
            def _extract() -> Dict[str, Any]:
                cmd = [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(file_path),
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    return json.loads(result.stdout)
                return {}
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _extract)
        except Exception as e:
            logger.warning("Failed to extract video metadata: %s", e)
            return {}


class AdvancedFileService:
    def __init__(self) -> None:
        self.config = app_config
        self.upload_dir = Path(self.config.UPLOAD_DIR)
        self.temp_dir = Path(tempfile.gettempdir()) / "filebot_temp"
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def save_file_metadata(self, filename: str, user_id: Optional[str] = None, subfolder: Optional[str] = None) -> str:
        is_valid, error_msg = FileValidator.validate_filename(filename)
        if not is_valid:
            raise ValidationError("filename", filename, error_msg)
        try:
            safe_filename = self._sanitize_filename(filename)
            folder_path = self._create_folder_structure(user_id, subfolder)
            unique_name = f"{uuid4().hex}_{safe_filename}"
            full_path = folder_path / unique_name
            logger.info("File metadata saved: %s", full_path)
            return str(full_path)
        except Exception as e:
            logger.error("Error saving file metadata: %s", e)
            raise FileOperationError(f"خطا در ذخیره metadata فایل: {e}")

    def _sanitize_filename(self, filename: str) -> str:
        sanitized = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", filename)
        if len(sanitized) > 200:
            name, ext = Path(sanitized).stem, Path(sanitized).suffix
            sanitized = name[: 200 - len(ext)] + ext
        return sanitized

    def _create_folder_structure(self, user_id: Optional[str] = None, subfolder: Optional[str] = None) -> Path:
        now = datetime.utcnow()
        date_path = now.strftime("%Y/%m/%d")
        if user_id:
            user_hash = hashlib.md5(user_id.encode()).hexdigest()[:8]
            folder_path = self.upload_dir / "users" / user_hash / date_path
        else:
            folder_path = self.upload_dir / "general" / date_path
        if subfolder:
            safe_subfolder = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", subfolder)
            folder_path = folder_path / safe_subfolder
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path

    async def process_uploaded_file(
        self,
        file_path: Path,
        user_id: str,
        session: AsyncSession,
        compress: bool = False,
        extract_metadata: bool = True,
    ) -> File:
        try:
            if not file_path.exists():
                raise FileOperationError("فایل یافت نشد")
            hashes = await FileHashManager.calculate_file_hashes(file_path)
            duplicates = await FileHashManager.find_duplicate_files(session, hashes["md5"])
            if duplicates:
                logger.info("Duplicate file found: %s", file_path)
            file_type, mime_type = FileValidator.detect_file_type(file_path)
            metadata: Dict[str, Any] = {}
            if extract_metadata:
                if file_type == FileType.IMAGE:
                    metadata = await FileMetadataExtractor.extract_image_metadata(file_path)
                elif file_type == FileType.VIDEO:
                    metadata = await FileMetadataExtractor.extract_video_metadata(file_path)
            compressed_path = None
            compression_ratio = 0.0
            if compress and file_type in [FileType.IMAGE, FileType.DOCUMENT]:
                compressed_path = await self._compress_file(file_path)
                if compressed_path:
                    original_size = file_path.stat().st_size
                    compressed_size = compressed_path.stat().st_size
                    compression_ratio = (1 - compressed_size / original_size) * 100
            file_record = File(
                user_id=user_id,
                original_file_name=file_path.name,
                sanitized_file_name=self._sanitize_filename(file_path.name),
                file_size=file_path.stat().st_size,
                file_type=file_type,
                mime_type=mime_type,
                storage_path=str(compressed_path or file_path),
                file_hash_md5=hashes["md5"],
                file_hash_sha256=hashes["sha256"],
                metadata=json.dumps(metadata) if metadata else None,
                status=FileStatus.READY,
                processed_at=datetime.utcnow(),
            )
            session.add(file_record)
            await session.flush()
            logger.info("File processed successfully: %s", file_record.id)
            return file_record
        except Exception as e:
            logger.error("Error processing file %s: %s", file_path, e)
            raise FileOperationError(f"خطا در پردازش فایل: {e}")

    async def _compress_file(self, file_path: Path) -> Optional[Path]:
        try:
            compressed_path = file_path.with_suffix(f"{file_path.suffix}.gz")
            def _compress() -> None:
                import gzip
                with open(file_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            await asyncio.get_event_loop().run_in_executor(self.executor, _compress)
            if compressed_path.exists():
                original_size = file_path.stat().st_size
                compressed_size = compressed_path.stat().st_size
                if compressed_size < original_size * 0.9:
                    file_path.unlink()
                    return compressed_path
                compressed_path.unlink()
            return None
        except Exception as e:
            logger.warning("File compression failed: %s", e)
            return None

    async def delete_file_safely(self, file_record: File, session: AsyncSession, permanent: bool = False) -> bool:
        try:
            if permanent:
                if Path(file_record.storage_path).exists():
                    Path(file_record.storage_path).unlink()
                await session.delete(file_record)
                logger.info("File permanently deleted: %s", file_record.id)
            else:
                file_record.deleted_at = datetime.utcnow()
                file_record.status = FileStatus.DELETED
                logger.info("File soft deleted: %s", file_record.id)
            return True
        except Exception as e:
            logger.error("Error deleting file %s: %s", file_record.id, e)
            return False

    async def get_file_statistics(self, session: AsyncSession, user_id: Optional[str] = None) -> Dict[str, Any]:
        base_query = select(func.count(File.id), func.sum(File.file_size))
        if user_id:
            base_query = base_query.where(File.user_id == user_id)
        base_query = base_query.where(File.deleted_at.is_(None))
        result = await session.execute(base_query)
        total_files, total_size = result.first()
        type_query = select(File.file_type, func.count(File.id)).group_by(File.file_type)
        if user_id:
            type_query = type_query.where(File.user_id == user_id)
        type_result = await session.execute(type_query)
        type_stats = dict(type_result.all())
        return {
            "total_files": total_files or 0,
            "total_size_bytes": total_size or 0,
            "total_size_mb": round((total_size or 0) / (1024 * 1024), 2),
            "by_type": {k.value if isinstance(k, Enum) else k: v for k, v in type_stats.items()},
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def cleanup_temp_files(self, older_than_hours: int = 24) -> int:
        cleanup_count = 0
        cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)
        try:
            for temp_file in self.temp_dir.rglob("*"):
                if temp_file.is_file():
                    file_time = datetime.fromtimestamp(temp_file.stat().st_mtime)
                    if file_time < cutoff_time:
                        temp_file.unlink()
                        cleanup_count += 1
            logger.info("Cleaned up %s temporary files", cleanup_count)
            return cleanup_count
        except Exception as e:
            logger.error("Error cleaning up temp files: %s", e)
            return 0

    async def create_file_archive(self, file_records: List[File], archive_name: str, user_id: str) -> Optional[str]:
        try:
            archive_path = await self.save_file_metadata(f"{archive_name}.zip", user_id, "archives")
            def _create_archive() -> None:
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for file_record in file_records:
                        path = Path(file_record.storage_path)
                        if path.exists():
                            zipf.write(path, file_record.original_file_name)
            await asyncio.get_event_loop().run_in_executor(self.executor, _create_archive)
            if Path(archive_path).exists():
                logger.info("Archive created: %s", archive_path)
                return archive_path
            return None
        except Exception as e:
            logger.error("Error creating archive: %s", e)
            return None

    async def extract_archive(self, archive_file: File, extract_to: Optional[str] = None) -> List[str]:
        extracted_files: List[str] = []
        archive_path = Path(archive_file.storage_path)
        if not archive_path.exists():
            raise FileOperationError("فایل آرشیو یافت نشد")
        if not extract_to:
            extract_to = archive_path.parent / f"extracted_{uuid4().hex}"
        extract_dir = Path(extract_to)
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            def _extract() -> List[str]:
                if archive_path.suffix.lower() == ".zip":
                    with zipfile.ZipFile(archive_path, "r") as zipf:
                        zipf.extractall(extract_dir)
                        return zipf.namelist()
                raise FileOperationError("نوع آرشیو پشتیبانی نمی‌شود")
            file_list = await asyncio.get_event_loop().run_in_executor(self.executor, _extract)
            for filename in file_list:
                extracted_path = extract_dir / filename
                if extracted_path.exists():
                    extracted_files.append(str(extracted_path))
            logger.info("Extracted %s files from archive", len(extracted_files))
            return extracted_files
        except Exception as e:
            logger.error("Error extracting archive: %s", e)
            raise FileOperationError(f"خطا در استخراج آرشیو: {e}")


file_service = AdvancedFileService()


async def save_file_metadata(filename: str, user_id: Optional[str] = None) -> str:
    return await file_service.save_file_metadata(filename, user_id)


async def process_uploaded_file(file_path: str, user_id: str, session: AsyncSession) -> File:
    return await file_service.process_uploaded_file(Path(file_path), user_id, session)


async def cleanup_old_files() -> int:
    try:
        cleanup_count = await file_service.cleanup_temp_files()
        logger.info("Background cleanup completed: %s files", cleanup_count)
        return cleanup_count
    except Exception as e:
        logger.error("Background cleanup failed: %s", e)
        return 0

