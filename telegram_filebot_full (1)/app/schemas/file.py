from pydantic import BaseModel, ConfigDict, Field, validator, root_validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum
import re
import mimetypes
from urllib.parse import urlparse
import validators


class FileTypeEnum(str, Enum):
    """Supported file types"""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    OTHER = "other"


class FileStatusEnum(str, Enum):
    """File status"""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    DELETED = "deleted"
    QUARANTINED = "quarantined"


class CompressionTypeEnum(str, Enum):
    """Compression type"""

    NONE = "none"
    GZIP = "gzip"
    LZ4 = "lz4"
    ZSTD = "zstd"


class FileSourceEnum(str, Enum):
    """File source"""

    TELEGRAM_UPLOAD = "telegram_upload"
    DIRECT_UPLOAD = "direct_upload"
    URL_DOWNLOAD = "url_download"
    API_UPLOAD = "api_upload"


class FileNameMixin(BaseModel):
    """Mixin for validating filenames"""

    @classmethod
    def validate_filename(cls, filename: str) -> str:
        if not filename or len(filename.strip()) == 0:
            raise ValueError("نام فایل نمی‌تواند خالی باشد")
        filename = filename.strip()
        if len(filename) > 255:
            raise ValueError("نام فایل بیش از 255 کاراکتر نمی‌تواند باشد")
        dangerous_chars = [
            "/",
            "\\",
            "..",
            "<",
            ">",
            ":",
            '"',
            "|",
            "?",
            "*",
            "\0",
            "\r",
            "\n",
            "\t",
            "$",
            "`",
            ";",
            "&",
            "(",
            ")",
            "{",
            "}",
            "[",
            "]",
            "!",
            "^",
            "~",
            "#",
            "%",
        ]
        for char in dangerous_chars:
            if char in filename:
                raise ValueError(f"نام فایل نمی‌تواند شامل '{char}' باشد")
        if "." not in filename:
            raise ValueError("نام فایل باید دارای پسوند باشد")
        extension = filename.split(".")[-1].lower()
        blocked_extensions = {
            "exe",
            "bat",
            "cmd",
            "sh",
            "msi",
            "dll",
            "scr",
            "ps1",
            "com",
            "pif",
            "application",
            "gadget",
            "msp",
            "msc",
            "vbs",
            "vbe",
            "js",
            "jse",
            "ws",
            "wsf",
            "wsc",
            "wsh",
        }
        if extension in blocked_extensions:
            raise ValueError(f"نوع فایل '{extension}' مجاز نیست")
        if not re.match(r"^[^.]+\.[a-zA-Z0-9]+$", filename):
            raise ValueError("فرمت نام فایل نامعتبر است")
        return filename


class FileCreate(FileNameMixin):
    """Schema for creating a new file"""

    original_file_name: str = Field(..., min_length=1, max_length=255, description="نام اصلی فایل")
    file_size: int = Field(..., gt=0, le=5 * 1024 * 1024 * 1024, description="اندازه فایل به بایت")
    source: FileSourceEnum = Field(default=FileSourceEnum.TELEGRAM_UPLOAD, description="منبع آپلود فایل")
    telegram_file_id: Optional[str] = Field(None, min_length=10, max_length=200, description="شناسه فایل در تلگرام")
    telegram_file_unique_id: Optional[str] = Field(None, min_length=10, max_length=200, description="شناسه منحصر به فرد فایل در تلگرام")
    is_from_link: bool = Field(default=False, description="آیا فایل از لینک دانلود شده")
    original_link: Optional[str] = Field(None, max_length=2048, description="لینک اصلی فایل")
    mime_type: Optional[str] = Field(None, max_length=100, description="نوع MIME فایل")
    description: Optional[str] = Field(None, max_length=1000, description="توضیحات فایل")
    tags: Optional[List[str]] = Field(default_factory=list, max_items=20, description="برچسب‌های فایل")
    is_public: bool = Field(default=False, description="دسترسی عمومی")
    access_expires_hours: Optional[int] = Field(None, gt=0, le=8760, description="انقضای دسترسی (ساعت)")
    enable_compression: bool = Field(default=False, description="فعال‌سازی فشرده‌سازی")
    compression_type: CompressionTypeEnum = Field(default=CompressionTypeEnum.NONE, description="نوع فشرده‌سازی")
    custom_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="اطلاعات اضافی سفارشی")

    @validator("original_file_name")
    def validate_file_name(cls, v: str) -> str:
        return cls.validate_filename(v)

    @validator("file_size")
    def validate_file_size_limits(cls, v: int, values) -> int:
        filename = values.get("original_file_name", "")
        if not filename:
            return v
        extension = filename.split(".")[-1].lower()
        size_limits = {
            "jpg": 100 * 1024 * 1024,
            "jpeg": 100 * 1024 * 1024,
            "png": 100 * 1024 * 1024,
            "gif": 50 * 1024 * 1024,
            "webp": 50 * 1024 * 1024,
            "mp4": 2 * 1024 * 1024 * 1024,
            "avi": 2 * 1024 * 1024 * 1024,
            "mkv": 2 * 1024 * 1024 * 1024,
            "mov": 1 * 1024 * 1024 * 1024,
            "mp3": 500 * 1024 * 1024,
            "wav": 500 * 1024 * 1024,
            "flac": 500 * 1024 * 1024,
            "pdf": 200 * 1024 * 1024,
            "doc": 100 * 1024 * 1024,
            "docx": 100 * 1024 * 1024,
            "zip": 1 * 1024 * 1024 * 1024,
            "rar": 1 * 1024 * 1024 * 1024,
            "7z": 1 * 1024 * 1024 * 1024,
        }
        max_size = size_limits.get(extension, 500 * 1024 * 1024)
        if v > max_size:
            raise ValueError(
                f"اندازه فایل {extension} نباید بیش از {max_size // (1024*1024)} مگابایت باشد"
            )
        return v

    @validator("telegram_file_id")
    def validate_telegram_file_id(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        if not re.match(r"^[A-Za-z0-9_-]+$", v):
            raise ValueError("فرمت شناسه فایل تلگرام نامعتبر است")
        return v

    @validator("original_link")
    def validate_original_link(cls, v: Optional[str], values) -> Optional[str]:
        is_from_link = values.get("is_from_link", False)
        if is_from_link and not v:
            raise ValueError("در صورت دانلود از لینک، آدرس لینک الزامی است")
        if v:
            if not validators.url(v):
                raise ValueError("فرمت لینک نامعتبر است")
            parsed = urlparse(v)
            if parsed.scheme not in ["http", "https", "ftp", "ftps"]:
                raise ValueError("پروتکل لینک مجاز نیست")
            blocked_domains = {
                "localhost",
                "127.0.0.1",
                "0.0.0.0",
                "192.168.",
                "10.",
                "172.16.",
            }
            hostname = parsed.hostname or ""
            if any(hostname.startswith(blocked) for blocked in blocked_domains):
                raise ValueError("دامنه لینک مجاز نیست")
        return v

    @validator("mime_type")
    def validate_mime_type(cls, v: Optional[str], values) -> Optional[str]:
        filename = values.get("original_file_name", "")
        if not v and filename:
            mime_type, _ = mimetypes.guess_type(filename)
            return mime_type
        if v and not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9!#$&\-\^]*\/[a-zA-Z0-9!#$&\-\^]*$", v):
            raise ValueError("فرمت MIME type نامعتبر است")
        return v

    @validator("tags")
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        if not v:
            return []
        validated_tags = []
        for tag in v:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if len(tag) == 0 or len(tag) > 50:
                continue
            if not re.match(r"^[a-zA-Z0-9\u0600-\u06FF\s\-_]+$", tag):
                continue
            validated_tags.append(tag)
        return list(set(validated_tags))

    @root_validator
    def validate_source_consistency(cls, values):
        source = values.get("source")
        telegram_file_id = values.get("telegram_file_id")
        is_from_link = values.get("is_from_link", False)
        original_link = values.get("original_link")
        if source == FileSourceEnum.TELEGRAM_UPLOAD and not telegram_file_id:
            raise ValueError("برای آپلود تلگرام، شناسه فایل الزامی است")
        if source == FileSourceEnum.URL_DOWNLOAD and not original_link:
            raise ValueError("برای دانلود از URL، لینک الزامی است")
        if is_from_link and not original_link:
            raise ValueError("در صورت دانلود از لینک، آدرس لینک الزامی است")
        return values


class FileLinkCreate(FileNameMixin):
    """Schema for creating a file from link"""

    url: str = Field(..., max_length=2048, description="آدرس لینک فایل")
    file_name: Optional[str] = Field(None, max_length=255, description="نام دلخواه فایل (اختیاری)")
    description: Optional[str] = Field(None, max_length=500, description="توضیحات فایل")
    tags: Optional[List[str]] = Field(default_factory=list, max_items=10, description="برچسب‌های فایل")
    max_file_size: int = Field(
        default=100 * 1024 * 1024,
        gt=0,
        le=2 * 1024 * 1024 * 1024,
        description="حداکثر اندازه قابل دانلود",
    )
    timeout_seconds: int = Field(
        default=300, gt=0, le=3600, description="timeout دانلود"
    )

    @validator("url")
    def validate_url(cls, v: str) -> str:
        if not validators.url(v):
            raise ValueError("فرمت URL نامعتبر است")
        parsed = urlparse(v)
        if parsed.scheme not in ["http", "https"]:
            raise ValueError("فقط پروتکل‌های HTTP و HTTPS مجاز هستند")
        if not parsed.hostname:
            raise ValueError("hostname معتبر ضروری است")
        blocked_domains = [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "10.0.0.0",
            "malware.com",
            "virus.com",
        ]
        hostname = parsed.hostname.lower()
        if any(hostname.startswith(blocked) for blocked in blocked_domains):
            raise ValueError("دامنه مورد نظر مجاز نیست")
        import ipaddress

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                raise ValueError("دسترسی به IP های محلی مجاز نیست")
        except ValueError:
            pass
        return v

    @validator("file_name")
    def validate_custom_filename(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return cls.validate_filename(v)
        return v


class FileUpdate(BaseModel):
    """Schema for updating file"""

    description: Optional[str] = Field(None, max_length=1000, description="توضیحات جدید")
    tags: Optional[List[str]] = Field(None, max_items=20, description="برچسب‌های جدید")
    is_public: Optional[bool] = Field(None, description="تغییر وضعیت عمومی")
    access_expires_hours: Optional[int] = Field(
        None, gt=0, le=8760, description="تغییر انقضای دسترسی"
    )
    custom_metadata: Optional[Dict[str, Any]] = Field(
        None, description="به‌روزرسانی اطلاعات اضافی"
    )

    @validator("tags")
    def validate_tags_update(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        return FileCreate.validate_tags(v)


class FileOut(BaseModel):
    """Schema for file output"""

    id: str = Field(description="شناسه منحصر به فرد فایل")
    original_file_name: str = Field(description="نام اصلی فایل")
    sanitized_file_name: str = Field(description="نام پاکسازی شده فایل")
    file_size: int = Field(description="اندازه فایل (بایت)")
    file_size_mb: float = Field(description="اندازه فایل (مگابایت)")
    file_type: FileTypeEnum = Field(description="نوع فایل")
    mime_type: Optional[str] = Field(description="نوع MIME")
    status: FileStatusEnum = Field(description="وضعیت فایل")
    is_safe: bool = Field(description="امنیت فایل")
    is_accessible: bool = Field(description="قابل دسترس بودن")
    download_token: str = Field(description="توکن دانلود امن")
    download_count: int = Field(description="تعداد دانلودها")
    is_compressed: bool = Field(description="فشرده شده یا خیر")
    compression_ratio: Optional[float] = Field(description="نسبت فشرده‌سازی")
    description: Optional[str] = Field(description="توضیحات فایل")
    tags: List[str] = Field(description="برچسب‌های فایل")
    metadata: Dict[str, Any] = Field(description="اطلاعات اضافی")
    created_at: datetime = Field(description="تاریخ ایجاد")
    updated_at: Optional[datetime] = Field(description="تاریخ آخرین به‌روزرسانی")
    last_downloaded_at: Optional[datetime] = Field(description="آخرین دانلود")
    access_expires_at: Optional[datetime] = Field(description="انقضای دسترسی")

    model_config = ConfigDict(from_attributes=True)


class FileDetailOut(FileOut):
    """Schema for detailed file info"""

    storage_path: str = Field(description="مسیر ذخیره‌سازی")
    telegram_file_id: Optional[str] = Field(description="شناسه تلگرام")
    original_link: Optional[str] = Field(description="لینک اصلی")
    upload_duration: Optional[float] = Field(description="مدت آپلود")
    processing_duration: Optional[float] = Field(description="مدت پردازش")
    file_hash_md5: Optional[str] = Field(description="MD5 hash")
    file_hash_sha256: Optional[str] = Field(description="SHA256 hash")
    is_virus_scanned: bool = Field(description="اسکن ویروس انجام شده")
    virus_scan_result: Optional[str] = Field(description="نتیجه اسکن ویروس")


class FileListOut(BaseModel):
    """Schema for paginated list of files"""

    files: List[FileOut] = Field(description="لیست فایل‌ها")
    total: int = Field(description="تعداد کل فایل‌ها")
    page: int = Field(description="شماره صفحه")
    per_page: int = Field(description="تعداد در هر صفحه")
    pages: int = Field(description="تعداد کل صفحات")
    has_next: bool = Field(description="صفحه بعدی موجود است")
    has_prev: bool = Field(description="صفحه قبلی موجود است")


class FileSearchQuery(BaseModel):
    """Schema for searching files"""

    query: Optional[str] = Field(None, max_length=200, description="کلمه کلیدی جستجو")
    file_type: Optional[FileTypeEnum] = Field(None, description="فیلتر نوع فایل")
    tags: Optional[List[str]] = Field(None, max_items=10, description="فیلتر برچسب‌ها")
    min_size: Optional[int] = Field(None, ge=0, description="حداقل اندازه (بایت)")
    max_size: Optional[int] = Field(None, gt=0, description="حداکثر اندازه (بایت)")
    date_from: Optional[datetime] = Field(None, description="از تاریخ")
    date_to: Optional[datetime] = Field(None, description="تا تاریخ")
    sort_by: Optional[str] = Field(
        "created_at",
        regex="^(created_at|file_size|download_count|name)$",
        description="مرتب‌سازی بر اساس",
    )
    sort_order: Optional[str] = Field(
        "desc", regex="^(asc|desc)$", description="ترتیب مرتب‌سازی"
    )
    page: int = Field(1, ge=1, description="شماره صفحه")
    per_page: int = Field(20, ge=1, le=100, description="تعداد در هر صفحه")

    @root_validator
    def validate_date_range(cls, values):
        date_from = values.get("date_from")
        date_to = values.get("date_to")
        if date_from and date_to and date_from >= date_to:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")
        return values

    @root_validator
    def validate_size_range(cls, values):
        min_size = values.get("min_size")
        max_size = values.get("max_size")
        if min_size and max_size and min_size >= max_size:
            raise ValueError("حداقل اندازه باید کمتر از حداکثر اندازه باشد")
        return values


class FileStatsOut(BaseModel):
    """Schema for file statistics"""

    total_files: int = Field(description="تعداد کل فایل‌ها")
    total_size_bytes: int = Field(description="حجم کل (بایت)")
    total_size_mb: float = Field(description="حجم کل (مگابایت)")
    total_downloads: int = Field(description="تعداد کل دانلودها")
    by_type: Dict[str, int] = Field(description="تعداد بر اساس نوع")
    by_status: Dict[str, int] = Field(description="تعداد بر اساس وضعیت")
    avg_file_size: float = Field(description="میانگین اندازه فایل")
    largest_file_size: int = Field(description="بزرگترین فایل")
    most_downloaded: int = Field(description="بیشترین دانلود")
    recent_uploads: int = Field(description="آپلودهای اخیر (24 ساعت)")
    recent_downloads: int = Field(description="دانلودهای اخیر (24 ساعت)")


class FileErrorResponse(BaseModel):
    """Schema for error responses"""

    error: bool = Field(True, description="وجود خطا")
    error_code: str = Field(description="کد خطا")
    message: str = Field(description="پیام خطا")
    details: Optional[Dict[str, Any]] = Field(description="جزئیات خطا")
    timestamp: datetime = Field(description="زمان خطا")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": True,
                "error_code": "FILE_TOO_LARGE",
                "message": "اندازه فایل بیش از حد مجاز است",
                "details": {"max_size": 104857600, "file_size": 209715200},
                "timestamp": "2025-06-11T20:30:00Z",
            }
        }
    )


class FileSuccessResponse(BaseModel):
    """Schema for successful responses"""

    success: bool = Field(True, description="موفقیت عملیات")
    message: str = Field(description="پیام موفقیت")
    data: Optional[Union[FileOut, FileDetailOut, FileListOut]] = Field(
        description="داده‌ها"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="زمان پاسخ"
    )

