from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, root_validator, validator

from app.models.user import BlockType, Language, UserRole, UserStatus


class UserValidationMixin:
    """Common validators used across user schemas."""

    @classmethod
    def validate_telegram_id_extended(cls, telegram_id: int) -> int:
        if telegram_id <= 0:
            raise ValueError("شناسه تلگرام باید مثبت باشد")
        if telegram_id > 9_999_999_999:
            raise ValueError("شناسه تلگرام خارج از محدوده مجاز است")
        if telegram_id in {777000, 1087968824}:
            raise ValueError("شناسه تلگرام محفوظ شده است")
        return telegram_id

    @classmethod
    def validate_username_extended(cls, username: Optional[str]) -> Optional[str]:
        if not username:
            return None
        username = username.strip().lstrip("@").lower()
        if len(username) < 5:
            raise ValueError("نام کاربری باید حداقل 5 کاراکتر باشد")
        if len(username) > 32:
            raise ValueError("نام کاربری نباید بیش از 32 کاراکتر باشد")
        if not re.match(r"^[a-zA-Z0-9_]+$", username):
            raise ValueError(
                "نام کاربری فقط می‌تواند شامل حروف انگلیسی، اعداد و _ باشد"
            )
        if username[0].isdigit() or username.startswith("_") or username.endswith("_"):
            raise ValueError("نام کاربری فرمت درستی ندارد")
        reserved = {
            "admin",
            "support",
            "help",
            "bot",
            "telegram",
            "api",
            "root",
            "system",
            "null",
            "undefined",
            "test",
        }
        if username in reserved:
            raise ValueError("نام کاربری محفوظ شده است")
        return username

    @classmethod
    def validate_name_field(cls, name: str, field_name: str) -> str:
        if not name or not name.strip():
            raise ValueError(f"{field_name} نمی‌تواند خالی باشد")
        name = name.strip()
        if len(name) > 100:
            raise ValueError(f"{field_name} نباید بیش از 100 کاراکتر باشد")
        dangerous = ["<", ">", '"', "'", "&", "\0", "\n", "\r", "\t"]
        for ch in dangerous:
            if ch in name:
                raise ValueError(f"{field_name} نمی‌تواند شامل کاراکتر '{ch}' باشد")
        return name


class UserCreate(UserValidationMixin, BaseModel):
    telegram_id: int = Field(..., gt=0, description="شناسه تلگرام")
    telegram_username: Optional[str] = Field(None, max_length=32)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    display_name: Optional[str] = Field(None, max_length=150)
    phone_number: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    language_code: Language = Field(default=Language.FA)
    timezone: str = Field(default="Asia/Tehran", max_length=50)
    bio: Optional[str] = Field(None, max_length=500)
    referral_code: Optional[str] = Field(None, max_length=20, regex=r"^[A-Z0-9]+$")
    client_info: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator("telegram_id")
    def _validate_tid(cls, v: int) -> int:
        return cls.validate_telegram_id_extended(v)

    @validator("telegram_username")
    def _validate_username(cls, v: Optional[str]) -> Optional[str]:
        return cls.validate_username_extended(v)

    @validator("first_name")
    def _validate_first(cls, v: str) -> str:
        return cls.validate_name_field(v, "نام")

    @validator("last_name")
    def _validate_last(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return cls.validate_name_field(v, "نام خانوادگی")
        return v

    @validator("email")
    def _validate_email(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v.lower()):
            raise ValueError("فرمت ایمیل نامعتبر است")
        return v.lower()

    @validator("phone_number")
    def _validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        phone = re.sub(r"[^\d+]", "", v)
        if not re.match(r"^\+?[1-9]\d{6,14}$", phone):
            raise ValueError("فرمت شماره تلفن نامعتبر است")
        return phone


class UserUpdate(UserValidationMixin, BaseModel):
    telegram_username: Optional[str] = Field(None, max_length=32)
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    display_name: Optional[str] = Field(None, max_length=150)
    bio: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=20)
    language_code: Optional[Language] = None
    timezone: Optional[str] = Field(None, max_length=50)

    @validator("telegram_username")
    def _validate_username(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return cls.validate_username_extended(v)
        return v

    @validator("first_name")
    def _validate_first(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return cls.validate_name_field(v, "نام")
        return v

    @validator("last_name")
    def _validate_last(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return cls.validate_name_field(v, "نام خانوادگی")
        return v


class UserAdminUpdate(BaseModel):
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None
    is_verified: Optional[bool] = None
    is_premium: Optional[bool] = None
    block_reason: Optional[str] = Field(None, max_length=500)
    block_type: Optional[BlockType] = None
    blocked_until: Optional[datetime] = None
    admin_notes: Optional[str] = Field(None, max_length=1000)


class UserOut(BaseModel):
    id: str = Field(description="شناسه")
    telegram_id: int = Field(description="شناسه تلگرام")
    telegram_username: Optional[str] = Field(description="نام کاربری تلگرام")
    first_name: str = Field(description="نام")
    last_name: Optional[str] = Field(description="نام خانوادگی")
    full_name_display: str = Field(description="نام کامل برای نمایش")
    role: UserRole = Field(description="نقش")
    status: UserStatus = Field(description="وضعیت")
    is_active: bool = Field(description="فعال")
    is_verified: bool = Field(description="تایید شده")
    is_premium: bool = Field(description="پریمیوم")
    account_age_days: int = Field(description="سن حساب")
    last_activity_at: Optional[datetime] = Field(description="آخرین فعالیت")
    created_at: datetime = Field(description="تاریخ عضویت")

    model_config = ConfigDict(from_attributes=True)


class UserDetailOut(UserOut):
    email: Optional[str] = Field(description="ایمیل")
    phone_number: Optional[str] = Field(description="شماره تلفن")
    language_code: Language = Field(description="زبان")
    timezone: str = Field(description="منطقه زمانی")
    bio: Optional[str] = Field(description="درباره")
    storage_used_mb: float = Field(description="حجم استفاده شده")
    total_files_count: int = Field(description="تعداد فایل‌ها")
    total_downloads: int = Field(description="کل دانلودها")
    message_count: int = Field(description="تعداد پیام‌ها")
    login_count: int = Field(description="تعداد ورود")
    referral_code: Optional[str] = Field(description="کد معرف")
    referral_count: int = Field(description="تعداد معرفی‌ها")
    first_seen_at: datetime = Field(description="اولین بازدید")
    last_seen_at: Optional[datetime] = Field(description="آخرین بازدید")
    updated_at: Optional[datetime] = Field(description="آخرین به‌روزرسانی")


class UserAdminOut(UserDetailOut):
    is_blocked: bool = Field(description="مسدود")
    block_type: Optional[BlockType] = Field(description="نوع مسدودیت")
    block_reason: Optional[str] = Field(description="دلیل مسدودیت")
    blocked_at: Optional[datetime] = Field(description="زمان مسدودیت")
    blocked_until: Optional[datetime] = Field(description="مسدود تا")
    blocked_by: Optional[str] = Field(description="مسدود شده توسط")
    security_score: Optional[int] = Field(description="امتیاز امنیتی")
    is_suspicious: bool = Field(description="مشکوک")
    device_info: Optional[Dict[str, Any]] = Field(description="اطلاعات دستگاه")
    admin_notes: Optional[str] = Field(description="یادداشت‌های ادمین")


class UserListOut(BaseModel):
    users: List[UserOut] = Field(description="لیست کاربران")
    total: int = Field(description="تعداد کل")
    page: int = Field(description="شماره صفحه")
    per_page: int = Field(description="تعداد در صفحه")
    pages: int = Field(description="تعداد کل صفحات")
    has_next: bool = Field(description="صفحه بعدی موجود")
    has_prev: bool = Field(description="صفحه قبلی موجود")


class UserSearchQuery(BaseModel):
    query: Optional[str] = Field(None, max_length=100, description="جستجو")
    role: Optional[UserRole] = Field(None, description="نقش")
    status: Optional[UserStatus] = Field(None, description="وضعیت")
    is_premium: Optional[bool] = Field(None, description="پریمیوم")
    is_verified: Optional[bool] = Field(None, description="تایید شده")
    is_blocked: Optional[bool] = Field(None, description="مسدود")
    created_from: Optional[datetime] = Field(None, description="عضو از تاریخ")
    created_to: Optional[datetime] = Field(None, description="عضو تا تاریخ")
    last_activity_from: Optional[datetime] = Field(None, description="فعال از تاریخ")
    sort_by: str = Field(
        default="created_at",
        regex=r"^(created_at|last_activity_at|total_files_count|storage_used_mb)$",
        description="مرتب‌سازی بر اساس",
    )
    sort_order: str = Field(default="desc", regex=r"^(asc|desc)$", description="ترتیب")
    page: int = Field(default=1, ge=1, description="شماره صفحه")
    per_page: int = Field(default=20, ge=1, le=100, description="تعداد در صفحه")

    @root_validator
    def _check_dates(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        start = values.get("created_from")
        end = values.get("created_to")
        if start and end and start >= end:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")
        return values


class UserStatsOut(BaseModel):
    total_users: int = Field(description="کل کاربران")
    active_users: int = Field(description="کاربران فعال")
    new_users_today: int = Field(description="کاربران جدید امروز")
    new_users_this_week: int = Field(description="کاربران جدید این هفته")
    by_role: Dict[str, int] = Field(description="تعداد بر اساس نقش")
    by_status: Dict[str, int] = Field(description="تعداد بر اساس وضعیت")
    by_language: Dict[str, int] = Field(description="تعداد بر اساس زبان")
    premium_users: int = Field(description="کاربران پریمیوم")
    verified_users: int = Field(description="کاربران تایید شده")
    blocked_users: int = Field(description="کاربران مسدود")
    avg_files_per_user: float = Field(description="میانگین فایل هر کاربر")
    avg_storage_per_user: float = Field(description="میانگین حجم هر کاربر")
    most_active_users: List[Dict[str, Any]] = Field(description="فعال‌ترین کاربران")


class UserActionRequest(BaseModel):
    action: str = Field(
        ..., regex=r"^(block|unblock|suspend|activate|verify|unverify|promote|demote|delete)$",
        description="نوع عملیات",
    )
    reason: Optional[str] = Field(None, max_length=500, description="دلیل")
    duration_hours: Optional[int] = Field(None, gt=0, le=8760, description="مدت")
    new_role: Optional[UserRole] = Field(None, description="نقش جدید")
    admin_notes: Optional[str] = Field(None, max_length=1000, description="یادداشت")


class UserErrorResponse(BaseModel):
    error: bool = Field(True, description="وجود خطا")
    error_code: str = Field(description="کد خطا")
    message: str = Field(description="پیام خطا")
    details: Optional[Dict[str, Any]] = Field(None, description="جزئیات")
    timestamp: datetime = Field(description="زمان")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": True,
                "error_code": "USER_BLOCKED",
                "message": "کاربر مسدود است",
                "details": {
                    "block_reason": "spam",
                    "blocked_until": "2025-07-01T10:00:00Z",
                },
                "timestamp": "2025-06-11T20:30:00Z",
            }
        }
    )


class UserSuccessResponse(BaseModel):
    success: bool = Field(True, description="موفقیت")
    message: str = Field(description="پیام")
    data: Optional[Union[UserOut, UserDetailOut, UserListOut]] = Field(
        None, description="داده‌ها"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="زمان")
