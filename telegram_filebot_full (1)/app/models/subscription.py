from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Numeric,
    DateTime,
    CheckConstraint,
    Index,
    UniqueConstraint,
    Text,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, List
import uuid
import json

from app.core.db import Base
from app.core.exceptions import ValidationError


class PlanType(Enum):
    """نوع پلن اشتراک"""

    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


class BillingCycle(Enum):
    """دوره صورتحساب"""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


def generate_secure_uuid() -> str:
    """تولید UUID امن"""

    return str(uuid.uuid4())


class SubscriptionPlan(Base):
    """مدل کامل پلن اشتراک"""

    __tablename__ = "subscription_plans"

    # Primary fields
    id = Column(String(36), primary_key=True, default=generate_secure_uuid)
    name = Column(String(100), nullable=False, unique=True)
    display_name = Column(String(150), nullable=False)
    description = Column(Text)
    plan_type = Column(SQLEnum(PlanType), nullable=False, default=PlanType.FREE)

    # Limits and quotas
    max_storage_mb = Column(Integer, nullable=False, default=100)
    max_files = Column(Integer, nullable=False, default=10)
    max_file_size_mb = Column(Integer, nullable=False, default=50)
    max_downloads_per_day = Column(Integer, default=100)
    max_api_calls_per_hour = Column(Integer, default=1000)

    # Pricing
    price = Column(Numeric(10, 2), nullable=False, default=0.00)
    currency = Column(String(3), nullable=False, default="USD")
    billing_cycle = Column(SQLEnum(BillingCycle), nullable=False, default=BillingCycle.MONTHLY)

    # Duration
    expiry_days = Column(Integer, nullable=False, default=30)
    trial_days = Column(Integer, default=0)

    # Features (JSON field for flexible features)
    features = Column(Text)
    restrictions = Column(Text)

    # Status and visibility
    is_active = Column(Boolean, default=True, nullable=False)
    is_visible = Column(Boolean, default=True, nullable=False)
    is_popular = Column(Boolean, default=False)

    # Priority and ordering
    sort_order = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)

    # Relationships
    subscriptions = relationship(
        "UserSubscription",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Table constraints
    __table_args__ = (
        CheckConstraint("max_storage_mb > 0", name="positive_storage"),
        CheckConstraint("max_files > 0", name="positive_files"),
        CheckConstraint("max_file_size_mb > 0", name="positive_file_size"),
        CheckConstraint("price >= 0", name="non_negative_price"),
        CheckConstraint("expiry_days > 0", name="positive_expiry"),
        CheckConstraint("trial_days >= 0", name="non_negative_trial"),
        CheckConstraint("sort_order >= 0", name="non_negative_sort"),
        UniqueConstraint("name", name="unique_plan_name"),
        Index("idx_subscription_plans_active", "is_active"),
        Index("idx_subscription_plans_visible", "is_visible"),
        Index("idx_subscription_plans_type", "plan_type"),
        Index("idx_subscription_plans_price", "price"),
        Index("idx_subscription_plans_sort", "sort_order"),
        Index("idx_subscription_plans_deleted", "deleted_at"),
    )

    @validates("name")
    def validate_name(self, key: str, name: str) -> str:
        """اعتبارسنجی نام پلن"""

        if not name or len(name.strip()) == 0:
            raise ValidationError("name", name, "نام پلن نمی‌تواند خالی باشد")
        if len(name) > 100:
            raise ValidationError("name", name, "نام پلن بیش از حد طولانی است")
        import re

        if not re.match(r"^[a-zA-Z0-9\s\-_]+$", name):
            raise ValidationError("name", name, "نام پلن شامل کاراکترهای نامعتبر است")
        return name.strip()

    @validates("max_storage_mb")
    def validate_storage(self, key: str, storage: int) -> int:
        """اعتبارسنجی حجم ذخیره‌سازی"""

        if storage <= 0:
            raise ValidationError("max_storage_mb", storage, "حجم ذخیره‌سازی باید مثبت باشد")
        if storage > 1024 * 1024:
            raise ValidationError("max_storage_mb", storage, "حجم ذخیره‌سازی بیش از حد مجاز است")
        return storage

    @validates("price")
    def validate_price(self, key: str, price: Any) -> Decimal:  # type: ignore[override]
        """اعتبارسنجی قیمت"""

        if price is None:
            return Decimal("0.00")
        if isinstance(price, (int, float)):
            price = Decimal(str(price))
        if price < 0:
            raise ValidationError("price", price, "قیمت نمی‌تواند منفی باشد")
        if price > Decimal("999999.99"):
            raise ValidationError("price", price, "قیمت بیش از حد مجاز است")
        return price

    @validates("currency")
    def validate_currency(self, key: str, currency: str) -> str:
        """اعتبارسنجی واحد پول"""

        valid_currencies = ["USD", "EUR", "IRR", "BTC", "ETH"]
        if currency not in valid_currencies:
            raise ValidationError(
                "currency",
                currency,
                f"واحد پول معتبر نیست. مجاز: {valid_currencies}",
            )
        return currency.upper()

    @hybrid_property
    def is_deleted(self) -> bool:
        """بررسی حذف soft"""

        return self.deleted_at is not None

    @hybrid_property
    def is_free(self) -> bool:
        """بررسی رایگان بودن"""

        return self.price == 0 or self.plan_type == PlanType.FREE

    @hybrid_property
    def is_premium(self) -> bool:
        """بررسی پریمیوم بودن"""

        return self.plan_type in [PlanType.PREMIUM, PlanType.ENTERPRISE]

    @hybrid_property
    def storage_gb(self) -> float:
        """حجم ذخیره‌سازی به گیگابایت"""

        return round(self.max_storage_mb / 1024, 2) if self.max_storage_mb else 0

    @hybrid_property
    def monthly_price(self) -> Decimal:
        """قیمت ماهانه"""

        if self.billing_cycle == BillingCycle.MONTHLY:
            return self.price
        if self.billing_cycle == BillingCycle.YEARLY:
            return round(self.price / 12, 2)
        if self.billing_cycle == BillingCycle.WEEKLY:
            return round(self.price * 4.33, 2)
        if self.billing_cycle == BillingCycle.DAILY:
            return round(self.price * 30, 2)
        return self.price

    def get_features(self) -> List[str]:
        """دریافت لیست ویژگی‌ها"""

        if not self.features:
            return []
        try:
            return json.loads(self.features)
        except json.JSONDecodeError:
            return []

    def set_features(self, features: List[str]) -> None:
        """تنظیم ویژگی‌ها"""

        self.features = json.dumps(features, ensure_ascii=False)

    def get_restrictions(self) -> Dict[str, Any]:
        """دریافت محدودیت‌ها"""

        if not self.restrictions:
            return {}
        try:
            return json.loads(self.restrictions)
        except json.JSONDecodeError:
            return {}

    def set_restrictions(self, restrictions: Dict[str, Any]) -> None:
        """تنظیم محدودیت‌ها"""

        self.restrictions = json.dumps(restrictions, ensure_ascii=False)

    def has_feature(self, feature: str) -> bool:
        """بررسی وجود ویژگی"""

        return feature in self.get_features()

    def add_feature(self, feature: str) -> None:
        """افزودن ویژگی"""

        features = self.get_features()
        if feature not in features:
            features.append(feature)
            self.set_features(features)

    def remove_feature(self, feature: str) -> None:
        """حذف ویژگی"""

        features = self.get_features()
        if feature in features:
            features.remove(feature)
            self.set_features(features)

    def calculate_total_price(self, months: int = 1) -> Decimal:
        """محاسبه قیمت کل"""

        if self.billing_cycle == BillingCycle.MONTHLY:
            return self.price * months
        if self.billing_cycle == BillingCycle.YEARLY:
            years = months / 12
            return self.price * Decimal(str(years))
        return self.monthly_price * months

    def is_upgrade_from(self, other_plan: "SubscriptionPlan") -> bool:
        """بررسی ارتقا"""

        if not other_plan:
            return True
        if self.price > other_plan.price:
            return True
        if self.max_storage_mb > other_plan.max_storage_mb or self.max_files > other_plan.max_files:
            return True
        return False

    def mark_as_deleted(self) -> None:
        """حذف soft"""

        self.deleted_at = datetime.utcnow()
        self.is_active = False
        self.is_visible = False

    def restore(self) -> None:
        """بازیابی پلن"""

        self.deleted_at = None
        self.is_active = True

    @classmethod
    def get_active_plans(cls, session, visible_only: bool = True) -> List["SubscriptionPlan"]:
        """دریافت پلن‌های فعال"""

        query = session.query(cls).filter(cls.is_active.is_(True), cls.deleted_at.is_(None))
        if visible_only:
            query = query.filter(cls.is_visible.is_(True))
        return query.order_by(cls.sort_order, cls.price).all()

    @classmethod
    def get_by_type(cls, session, plan_type: PlanType) -> List["SubscriptionPlan"]:
        """دریافت پلن‌ها بر اساس نوع"""

        return (
            session.query(cls)
            .filter(cls.plan_type == plan_type, cls.is_active.is_(True), cls.deleted_at.is_(None))
            .all()
        )

    @classmethod
    def get_free_plan(cls, session) -> "SubscriptionPlan | None":
        """دریافت پلن رایگان"""

        return (
            session.query(cls)
            .filter(cls.plan_type == PlanType.FREE, cls.is_active.is_(True), cls.deleted_at.is_(None))
            .first()
        )

    @classmethod
    def create_default_plans(cls, session) -> None:
        """ایجاد پلن‌های پیش‌فرض"""

        default_plans = [
            {
                "name": "Free",
                "display_name": "پلن رایگان",
                "description": "پلن رایگان با امکانات محدود",
                "plan_type": PlanType.FREE,
                "max_storage_mb": 100,
                "max_files": 10,
                "max_file_size_mb": 25,
                "price": Decimal("0.00"),
                "expiry_days": 3650,
                "features": ["basic_upload", "basic_download"],
                "sort_order": 1,
            },
            {
                "name": "Basic",
                "display_name": "پلن پایه",
                "description": "پلن پایه برای کاربران عادی",
                "plan_type": PlanType.BASIC,
                "max_storage_mb": 1024,
                "max_files": 100,
                "max_file_size_mb": 100,
                "price": Decimal("9.99"),
                "expiry_days": 30,
                "features": ["unlimited_downloads", "priority_support"],
                "sort_order": 2,
            },
            {
                "name": "Premium",
                "display_name": "پلن پریمیوم",
                "description": "پلن پریمیوم با تمام امکانات",
                "plan_type": PlanType.PREMIUM,
                "max_storage_mb": 10240,
                "max_files": 1000,
                "max_file_size_mb": 500,
                "price": Decimal("29.99"),
                "expiry_days": 30,
                "features": ["unlimited_everything", "api_access", "custom_domain"],
                "is_popular": True,
                "sort_order": 3,
            },
        ]

        for plan_data in default_plans:
            features = plan_data.pop("features", [])
            plan = cls(**plan_data)
            plan.set_features(features)
            session.add(plan)

    def to_dict(self, include_deleted: bool = False) -> Dict[str, Any]:
        """تبدیل به dictionary"""

        if self.is_deleted and not include_deleted:
            return {}
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "plan_type": self.plan_type.value,
            "max_storage_mb": self.max_storage_mb,
            "max_files": self.max_files,
            "max_file_size_mb": self.max_file_size_mb,
            "storage_gb": self.storage_gb,
            "price": float(self.price),
            "monthly_price": float(self.monthly_price),
            "currency": self.currency,
            "billing_cycle": self.billing_cycle.value,
            "expiry_days": self.expiry_days,
            "trial_days": self.trial_days,
            "features": self.get_features(),
            "restrictions": self.get_restrictions(),
            "is_active": self.is_active,
            "is_visible": self.is_visible,
            "is_popular": self.is_popular,
            "is_free": self.is_free,
            "is_premium": self.is_premium,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<SubscriptionPlan(id='{self.id}', name='{self.name}', price={self.price})>"
