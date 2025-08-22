from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    Enum as SQLEnum,
    BigInteger,
    Float,
    JSON,
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any
import uuid
import hashlib
import os
import secrets
from pathlib import Path

from app.core.db import Base
from app.core.exceptions import ValidationError


class FileStatus(Enum):
    """وضعیت فایل"""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    DELETED = "deleted"
    QUARANTINED = "quarantined"


class FileType(Enum):
    """نوع فایل"""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    OTHER = "other"


class CompressionType(Enum):
    """نوع فشرده‌سازی"""

    NONE = "none"
    GZIP = "gzip"
    LZ4 = "lz4"
    ZSTD = "zstd"


def generate_secure_id() -> str:
    """تولید ID امن"""

    return str(uuid.uuid4())


def generate_secure_token() -> str:
    """تولید token امن برای دانلود"""

    return secrets.token_urlsafe(32)


class File(Base):
    """مدل پیشرفته فایل با امکانات امنیتی و عملکردی"""

    __tablename__ = "files"

    # Primary fields
    id = Column(String(36), primary_key=True, default=generate_secure_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # File information
    original_file_name = Column(String(255), nullable=False)
    sanitized_file_name = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_type = Column(SQLEnum(FileType), nullable=False, default=FileType.OTHER)
    mime_type = Column(String(100))
    file_extension = Column(String(10))

    # Storage information
    storage_path = Column(Text, nullable=False)
    relative_path = Column(String(500))
    compressed_size = Column(BigInteger)
    compression_type = Column(SQLEnum(CompressionType), default=CompressionType.NONE)

    # Security fields
    file_hash_md5 = Column(String(32))
    file_hash_sha256 = Column(String(64))
    download_token = Column(String(64), default=generate_secure_token, unique=True)
    is_virus_scanned = Column(Boolean, default=False)
    virus_scan_result = Column(String(50))

    # Download and access
    direct_download_url = Column(Text)
    download_count = Column(Integer, default=0)
    last_downloaded_at = Column(DateTime)
    access_expires_at = Column(DateTime)

    # Source information
    is_from_link = Column(Boolean, default=False)
    original_link = Column(Text)
    telegram_file_id = Column(String(200))
    telegram_file_unique_id = Column(String(200))

    # Status and metadata
    status = Column(SQLEnum(FileStatus), default=FileStatus.UPLOADING, nullable=False)
    metadata = Column(JSON)
    tags = Column(JSON)
    description = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)
    processed_at = Column(DateTime)

    # Performance metrics
    upload_duration = Column(Float)
    processing_duration = Column(Float)

    # Relationships
    user = relationship("User", back_populates="files")

    # Table constraints
    __table_args__ = (
        CheckConstraint("file_size > 0", name="positive_file_size"),
        CheckConstraint("download_count >= 0", name="non_negative_download_count"),
        CheckConstraint(
            "virus_scan_result IN ('clean', 'infected', 'suspicious', 'pending', 'error')",
            name="valid_virus_scan_result",
        ),
        Index("idx_files_user_id", "user_id"),
        Index("idx_files_created_at", "created_at"),
        Index("idx_files_status", "status"),
        Index("idx_files_file_type", "file_type"),
        Index("idx_files_user_status", "user_id", "status"),
        Index("idx_files_hash_md5", "file_hash_md5"),
        Index("idx_files_download_token", "download_token"),
        Index("idx_files_telegram_file_id", "telegram_file_id"),
        Index("idx_files_deleted_at", "deleted_at"),
        # Indexes for sorting
        Index("idx_files_user_size", "user_id", "file_size"),
        Index("idx_files_user_name", "user_id", "original_file_name"),
    )

    @validates("original_file_name")
    def validate_filename(self, key: str, filename: str) -> str:
        """اعتبارسنجی نام فایل"""

        if not filename or len(filename.strip()) == 0:
            raise ValidationError("filename", filename, "نام فایل نمی‌تواند خالی باشد")
        if len(filename) > 255:
            raise ValidationError("filename", filename, "نام فایل بیش از حد طولانی است")
        dangerous_chars = ["/", "\\", "..", "<", ">", ":", '"', "|", "?", "*", "\0"]
        for char in dangerous_chars:
            if char in filename:
                raise ValidationError(
                    "filename",
                    filename,
                    f"نام فایل نمی‌تواند شامل '{char}' باشد",
                )
        return filename.strip()

    @validates("file_size")
    def validate_file_size(self, key: str, size: int) -> int:
        """اعتبارسنجی اندازه فایل"""

        if size <= 0:
            raise ValidationError("file_size", size, "اندازه فایل باید مثبت باشد")
        max_size = 5 * 1024 * 1024 * 1024
        if size > max_size:
            raise ValidationError("file_size", size, "اندازه فایل بیش از حد مجاز است")
        return size

    @validates("storage_path")
    def validate_storage_path(self, key: str, path: str) -> str:
        """اعتبارسنجی مسیر ذخیره‌سازی"""

        if not path:
            raise ValidationError("storage_path", path, "مسیر ذخیره‌سازی الزامی است")
        abs_path = os.path.abspath(path)
        if ".." in path or path.startswith("/"):
            raise ValidationError("storage_path", path, "مسیر ذخیره‌سازی نامعتبر است")
        return abs_path

    @hybrid_property
    def is_deleted(self) -> bool:
        """بررسی حذف soft"""

        return self.deleted_at is not None

    @hybrid_property
    def file_size_mb(self) -> float:
        """اندازه فایل به مگابایت"""

        return round(self.file_size / (1024 * 1024), 2) if self.file_size else 0

    @hybrid_property
    def is_compressed(self) -> bool:
        """بررسی فشرده بودن فایل"""

        return self.compression_type != CompressionType.NONE

    @hybrid_property
    def compression_ratio(self) -> float:
        """نسبت فشرده‌سازی"""

        if self.compressed_size and self.file_size:
            return round((1 - self.compressed_size / self.file_size) * 100, 1)
        return 0

    @hybrid_property
    def is_safe(self) -> bool:
        """بررسی امنیت فایل"""

        return (
            self.is_virus_scanned
            and self.virus_scan_result == "clean"
            and self.status == FileStatus.READY
        )

    @hybrid_property
    def is_accessible(self) -> bool:
        """بررسی قابل دسترس بودن فایل"""

        if self.is_deleted:
            return False
        if self.access_expires_at and datetime.utcnow() > self.access_expires_at:
            return False
        return self.status == FileStatus.READY

    def generate_new_download_token(self) -> str:
        """تولید token دانلود جدید"""

        self.download_token = generate_secure_token()
        return self.download_token

    def set_file_hash(self, file_path: str) -> None:
        """محاسبه و تنظیم hash فایل"""

        try:
            md5_hash = hashlib.md5()
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    md5_hash.update(chunk)
                    sha256_hash.update(chunk)
            self.file_hash_md5 = md5_hash.hexdigest()
            self.file_hash_sha256 = sha256_hash.hexdigest()
        except Exception as e:  # pragma: no cover - simple pass-through
            raise ValidationError("file_hash", file_path, f"خطا در محاسبه hash فایل: {e}")

    def detect_file_type(self) -> FileType:
        """تشخیص نوع فایل بر اساس extension"""

        if not self.file_extension:
            return FileType.OTHER
        ext = self.file_extension.lower()
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
        video_exts = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv", ".wmv"}
        audio_exts = {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".wma"}
        doc_exts = {".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
        archive_exts = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}
        if ext in image_exts:
            return FileType.IMAGE
        if ext in video_exts:
            return FileType.VIDEO
        if ext in audio_exts:
            return FileType.AUDIO
        if ext in doc_exts:
            return FileType.DOCUMENT
        if ext in archive_exts:
            return FileType.ARCHIVE
        return FileType.OTHER

    def sanitize_filename(self) -> None:
        """پاکسازی نام فایل"""

        import re

        filename = self.original_file_name
        filename = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", filename)
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[: 200 - len(ext)] + ext
        if "." not in filename:
            filename += ".bin"
        self.sanitized_file_name = filename
        self.file_extension = Path(filename).suffix.lower()
        self.file_type = self.detect_file_type()

    def mark_as_deleted(self) -> None:
        """حذف soft فایل"""

        self.deleted_at = datetime.utcnow()
        self.status = FileStatus.DELETED

    def restore(self) -> None:
        """بازیابی فایل حذف شده"""

        self.deleted_at = None
        if self.status == FileStatus.DELETED:
            self.status = FileStatus.READY

    def increment_download_count(self) -> None:
        """افزایش شمارنده دانلود"""

        self.download_count = (self.download_count or 0) + 1
        self.last_downloaded_at = datetime.utcnow()

    def set_access_expiry(self, hours: int) -> None:
        """تنظیم انقضای دسترسی"""

        self.access_expires_at = datetime.utcnow() + timedelta(hours=hours)

    def update_metadata(self, new_metadata: Dict[str, Any]) -> None:
        """به‌روزرسانی metadata"""

        if self.metadata:
            self.metadata.update(new_metadata)
        else:
            self.metadata = new_metadata
        self.updated_at = datetime.utcnow()

    def add_tag(self, tag: str) -> None:
        """افزودن برچسب"""

        if not self.tags:
            self.tags = []
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """حذف برچسب"""

        if self.tags and tag in self.tags:
            self.tags.remove(tag)

    @classmethod
    def find_duplicates_by_hash(cls, session, md5_hash: str):
        """پیدا کردن فایل‌های تکراری بر اساس hash"""

        return (
            session.query(cls)
            .filter(cls.file_hash_md5 == md5_hash, cls.deleted_at.is_(None))
            .all()
        )

    @classmethod
    def get_user_files_stats(cls, session, user_id: str) -> Dict[str, Any]:
        """آمار فایل‌های کاربر"""

        from sqlalchemy import func

        result = (
            session.query(
                func.count(cls.id).label("total_files"),
                func.sum(cls.file_size).label("total_size"),
                func.avg(cls.file_size).label("avg_size"),
            )
            .filter(cls.user_id == user_id, cls.deleted_at.is_(None))
            .first()
        )
        return {
            "total_files": result.total_files or 0,
            "total_size": result.total_size or 0,
            "average_size": result.avg_size or 0,
            "total_size_mb": round((result.total_size or 0) / (1024 * 1024), 2),
        }

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """تبدیل به dictionary"""

        data = {
            "id": self.id,
            "original_file_name": self.original_file_name,
            "sanitized_file_name": self.sanitized_file_name,
            "file_size": self.file_size,
            "file_size_mb": self.file_size_mb,
            "file_type": self.file_type.value,
            "mime_type": self.mime_type,
            "status": self.status.value,
            "download_count": self.download_count,
            "created_at": self.created_at.isoformat(),
            "is_compressed": self.is_compressed,
            "compression_ratio": self.compression_ratio,
            "is_safe": self.is_safe,
            "is_accessible": self.is_accessible,
            "tags": self.tags or [],
            "metadata": self.metadata or {},
        }
        if include_sensitive:
            data.update(
                {
                    "storage_path": self.storage_path,
                    "download_token": self.download_token,
                    "file_hash_md5": self.file_hash_md5,
                    "direct_download_url": self.direct_download_url,
                }
            )
        return data

    def __repr__(self) -> str:
        return f"<File(id='{self.id}', name='{self.original_file_name}', size={self.file_size})>"
