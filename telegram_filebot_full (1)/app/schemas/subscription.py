from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, validator, root_validator


# ================================================
# Enums
# ================================================
class SubscriptionStatus(str, Enum):
    """وضعیت اشتراک"""

    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"
    REFUNDED = "refunded"
    TRIAL = "trial"


class PaymentStatus(str, Enum):
    """وضعیت پرداخت"""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PlanType(str, Enum):
    """نوع پلن"""

    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


class BillingCycle(str, Enum):
    """دوره صورتحساب"""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class SubscriptionType(str, Enum):
    """نوع اشتراک"""

    NEW = "new"
    RENEWAL = "renewal"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"


# ================================================
# Mixins
# ================================================
class BaseSubscriptionMixin:
    """Validation helpers"""

    @classmethod
    def validate_user_id(cls, user_id: str) -> str:
        if not user_id or len(user_id.strip()) == 0:
            raise ValueError("شناسه کاربر نمی‌تواند خالی باشد")
        import re

        pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        if not re.match(pattern, user_id.lower()):
            raise ValueError("فرمت شناسه کاربر نامعتبر است")
        return user_id.strip()

    @classmethod
    def validate_plan_id(cls, plan_id: str) -> str:
        if not plan_id or len(plan_id.strip()) == 0:
            raise ValueError("شناسه پلن نمی‌تواند خالی باشد")
        import re

        pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        if not re.match(pattern, plan_id.lower()):
            raise ValueError("فرمت شناسه پلن نامعتبر است")
        return plan_id.strip()


# ================================================
# Subscription Plan Schemas
# ================================================
class SubscriptionPlanCreate(BaseModel):
    """Schema برای ایجاد پلن اشتراک"""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=1000)
    plan_type: PlanType = Field(default=PlanType.BASIC)
    max_storage_mb: int = Field(..., gt=0, le=1024 * 1024)
    max_files: int = Field(..., gt=0, le=1_000_000)
    max_file_size_mb: int = Field(default=100, gt=0, le=5120)
    max_downloads_per_day: Optional[int] = Field(default=1000, ge=0)
    max_api_calls_per_hour: Optional[int] = Field(default=1000, ge=0)
    price: Decimal = Field(default=Decimal("0.00"), ge=0, le=Decimal("999999.99"))
    currency: str = Field(default="USD", regex="^[A-Z]{3}$")
    billing_cycle: BillingCycle = Field(default=BillingCycle.MONTHLY)
    expiry_days: int = Field(default=30, gt=0, le=36500)
    trial_days: int = Field(default=0, ge=0, le=365)
    features: List[str] = Field(default_factory=list, max_items=50)
    restrictions: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = Field(default=True)
    is_visible: bool = Field(default=True)
    is_popular: bool = Field(default=False)
    sort_order: int = Field(default=0, ge=0)

    @validator("name")
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("نام پلن نمی‌تواند خالی باشد")
        import re

        if not re.match(r"^[a-zA-Z0-9\s\-_\u0600-\u06FF]+$", v):
            raise ValueError("نام پلن شامل کاراکترهای نامعتبر است")
        return v

    @validator("features")
    def validate_features(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for feature in v:
            if isinstance(feature, str) and feature.strip():
                feature = feature.strip()
                if len(feature) <= 100:
                    cleaned.append(feature)
        return list(set(cleaned))

    @validator("currency")
    def validate_currency(cls, v: str) -> str:
        valid_currencies = ["USD", "EUR", "IRR", "BTC", "ETH", "USDT"]
        if v not in valid_currencies:
            raise ValueError(f"واحد پول معتبر نیست. مجاز: {valid_currencies}")
        return v


class SubscriptionPlanUpdate(BaseModel):
    """Schema برای به‌روزرسانی پلن"""

    display_name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=1000)
    max_storage_mb: Optional[int] = Field(None, gt=0, le=1024 * 1024)
    max_files: Optional[int] = Field(None, gt=0, le=1_000_000)
    max_file_size_mb: Optional[int] = Field(None, gt=0, le=5120)
    max_downloads_per_day: Optional[int] = Field(None, ge=0)
    price: Optional[Decimal] = Field(None, ge=0, le=Decimal("999999.99"))
    features: Optional[List[str]] = Field(None, max_items=50)
    is_active: Optional[bool] = None
    is_visible: Optional[bool] = None
    is_popular: Optional[bool] = None
    sort_order: Optional[int] = Field(None, ge=0)


class SubscriptionPlanOut(BaseModel):
    """Schema برای نمایش پلن"""

    id: str = Field(description="شناسه پلن")
    name: str = Field(description="نام پلن")
    display_name: str = Field(description="نام نمایشی")
    description: Optional[str] = Field(description="توضیحات")
    plan_type: PlanType = Field(description="نوع پلن")
    max_storage_mb: int = Field(description="حداکثر فضای ذخیره‌سازی")
    max_files: int = Field(description="حداکثر فایل")
    max_file_size_mb: int = Field(description="حداکثر اندازه فایل")
    storage_gb: float = Field(description="حجم ذخیره سازی گیگابایت")
    price: float = Field(description="قیمت")
    monthly_price: float = Field(description="قیمت ماهانه")
    currency: str = Field(description="واحد پول")
    billing_cycle: BillingCycle = Field(description="دوره صورتحساب")
    expiry_days: int = Field(description="مدت اعتبار")
    trial_days: int = Field(description="آزمایشی")
    features: List[str] = Field(description="ویژگی‌ها")
    is_active: bool = Field(description="فعال")
    is_visible: bool = Field(description="نمایش")
    is_popular: bool = Field(description="محبوب")
    is_free: bool = Field(description="رایگان")
    is_premium: bool = Field(description="پریمیوم")
    created_at: datetime = Field(description="ایجاد")
    updated_at: Optional[datetime] = Field(description="به‌روزرسانی")

    model_config = ConfigDict(from_attributes=True)


# ================================================
# User Subscription Schemas
# ================================================
class UserSubscriptionCreate(BaseSubscriptionMixin, BaseModel):
    """Schema برای ایجاد اشتراک کاربر"""

    user_id: str = Field(..., description="شناسه کاربر")
    plan_id: str = Field(..., description="شناسه پلن")
    subscription_type: SubscriptionType = Field(default=SubscriptionType.NEW)
    start_date: Optional[datetime] = Field(None)
    end_date: Optional[datetime] = Field(None)
    is_trial: bool = Field(default=False)
    trial_end_date: Optional[datetime] = Field(None)
    amount_paid: Optional[Decimal] = Field(default=Decimal("0.00"), ge=0)
    payment_method: Optional[str] = Field(None, max_length=50)
    transaction_id: Optional[str] = Field(None, max_length=100)
    auto_renewal: bool = Field(default=True)
    previous_subscription_id: Optional[str] = Field(None)
    discount_code: Optional[str] = Field(None, max_length=50)

    @validator("user_id")
    def validate_user_id_format(cls, v: str) -> str:
        return cls.validate_user_id(v)

    @validator("plan_id")
    def validate_plan_id_format(cls, v: str) -> str:
        return cls.validate_plan_id(v)

    @root_validator
    def validate_dates(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        start_date = values.get("start_date") or datetime.utcnow()
        end_date = values.get("end_date")
        trial_end = values.get("trial_end_date")
        is_trial = values.get("is_trial", False)
        values["start_date"] = start_date

        if end_date:
            if end_date <= start_date:
                raise ValueError("تاریخ پایان باید بعد از تاریخ شروع باشد")
            max_end = start_date + timedelta(days=3650)
            if end_date > max_end:
                raise ValueError("مدت اشتراک نمی‌تواند بیش از 10 سال باشد")
        if is_trial:
            if not trial_end:
                raise ValueError("برای اشتراک آزمایشی تاریخ پایان لازم است")
            if trial_end <= start_date:
                raise ValueError("تاریخ پایان آزمایش باید بعد از شروع باشد")
        return values


class UserSubscriptionUpdate(BaseModel):
    """Schema برای به‌روزرسانی اشتراک"""

    end_date: Optional[datetime] = Field(None)
    auto_renewal: Optional[bool] = None
    status: Optional[SubscriptionStatus] = None
    payment_status: Optional[PaymentStatus] = None
    cancellation_reason: Optional[str] = Field(None, max_length=500)
    admin_notes: Optional[str] = Field(None, max_length=1000)


class UserSubscriptionOut(BaseModel):
    """خروجی اشتراک کاربر"""

    id: str = Field(description="شناسه اشتراک")
    user_id: str = Field(description="شناسه کاربر")
    plan_id: str = Field(description="شناسه پلن")
    status: SubscriptionStatus = Field(description="وضعیت")
    subscription_type: SubscriptionType = Field(description="نوع")
    payment_status: PaymentStatus = Field(description="وضعیت پرداخت")
    start_date: datetime = Field(description="شروع")
    end_date: datetime = Field(description="پایان")
    created_at: datetime = Field(description="ایجاد")
    is_active: bool = Field(description="فعال")
    is_expired: bool = Field(description="منقضی")
    days_remaining: int = Field(description="روزهای باقی‌مانده")
    hours_remaining: int = Field(description="ساعات باقی‌مانده")
    is_trial: bool = Field(description="آزمایشی")
    trial_end_date: Optional[datetime] = Field(description="پایان آزمایش")
    auto_renewal: bool = Field(description="تمدید خودکار")
    next_billing_date: Optional[datetime] = Field(description="بدهی بعدی")
    amount_paid: float = Field(description="مبلغ پرداختی")
    currency: str = Field(description="واحد پول")

    model_config = ConfigDict(from_attributes=True)


class UserSubscriptionDetail(BaseModel):
    """جزئیات کامل اشتراک"""

    id: str = Field(description="شناسه اشتراک")
    user_id: str = Field(description="شناسه کاربر")
    plan: SubscriptionPlanOut = Field(description="جزئیات پلن")
    status: SubscriptionStatus = Field(description="وضعیت")
    subscription_type: SubscriptionType = Field(description="نوع اشتراک")
    payment_status: PaymentStatus = Field(description="وضعیت پرداخت")
    start_date: datetime = Field(description="تاریخ شروع")
    end_date: datetime = Field(description="تاریخ پایان")
    created_at: datetime = Field(description="ایجاد")
    updated_at: Optional[datetime] = Field(description="به‌روزرسانی")
    is_active: bool = Field(description="فعال")
    is_expired: bool = Field(description="منقضی")
    days_remaining: int = Field(description="روز باقی‌مانده")
    hours_remaining: int = Field(description="ساعت باقی‌مانده")
    account_age_days: int = Field(description="سن اشتراک (روز)")
    storage_used_mb: int = Field(default=0, description="حجم مصرف شده")
    files_count: int = Field(default=0, description="تعداد فایل‌ها")
    downloads_today: int = Field(default=0, description="دانلودهای امروز")
    storage_usage_percentage: float = Field(description="درصد استفاده حجم")
    files_usage_percentage: float = Field(description="درصد استفاده فایل")
    storage_limit_reached: bool = Field(description="محدودیت حجم")
    files_limit_reached: bool = Field(description="محدودیت فایل")
    is_trial: bool = Field(description="آزمایشی")
    trial_end_date: Optional[datetime] = Field(description="پایان آزمایش")
    is_trial_active: bool = Field(description="آزمایش فعال")
    auto_renewal: bool = Field(description="تمدید خودکار")
    needs_renewal_reminder: bool = Field(description="نیاز به یادآوری")
    amount_paid: float = Field(description="مبلغ پرداختی")
    can_upgrade: bool = Field(description="می‌توان ارتقا داد")
    can_downgrade: bool = Field(description="می‌توان تنزل داد")
    upgrade_credit: float = Field(default=0, description="اعتبار ارتقا")

    model_config = ConfigDict(from_attributes=True)


# ================================================
# Additional Schemas
# ================================================
class SubscriptionStatsOut(BaseModel):
    """آمار اشتراک‌ها"""

    total_subscriptions: int = Field(description="کل اشتراک‌ها")
    active_subscriptions: int = Field(description="اشتراک‌های فعال")
    expired_subscriptions: int = Field(description="اشتراک‌های منقضی")
    trial_subscriptions: int = Field(description="آزمایشی")
    total_revenue: float = Field(description="کل درآمد")
    monthly_revenue: float = Field(description="درآمد ماهانه")
    popular_plans: List[Dict[str, Any]] = Field(description="پلن‌های محبوب")
    conversion_rate: float = Field(description="نرخ تبدیل")
    by_status: Dict[str, int] = Field(description="بر اساس وضعیت")
    by_plan: Dict[str, int] = Field(description="بر اساس پلن")


class SubscriptionListQuery(BaseModel):
    """پارامترهای جستجو"""

    status: Optional[SubscriptionStatus] = Field(None)
    plan_id: Optional[str] = Field(None)
    is_trial: Optional[bool] = Field(None)
    expiring_days: Optional[int] = Field(None, ge=0, le=365)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
    sort_by: str = Field(default="created_at", regex="^(created_at|end_date|amount_paid|status)$")
    sort_order: str = Field(default="desc", regex="^(asc|desc)$")


class SubscriptionActionRequest(BaseModel):
    """درخواست عملیات"""

    action: str = Field(..., regex="^(activate|suspend|cancel|extend|refund)$")
    reason: Optional[str] = Field(None, max_length=500)
    extend_days: Optional[int] = Field(None, gt=0, le=365)
    refund_amount: Optional[Decimal] = Field(None, ge=0)
    admin_notes: Optional[str] = Field(None, max_length=1000)


class SubscriptionErrorResponse(BaseModel):
    """پاسخ خطا"""

    error: bool = Field(True)
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": True,
                "error_code": "SUBSCRIPTION_EXPIRED",
                "message": "اشتراک شما منقضی شده است",
                "details": {"expiry_date": "2025-06-01T10:00:00Z"},
                "timestamp": "2025-06-11T20:30:00Z",
            }
        }
    )
