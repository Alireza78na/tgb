from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Numeric,
    CheckConstraint,
    Index,
    UniqueConstraint,
    Text,
    Enum as SQLEnum,
    Integer,
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, Any
import uuid

from app.core.db import Base
from app.core.exceptions import ValidationError


class SubscriptionStatus(Enum):
    """وضعیت اشتراک"""

    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"
    REFUNDED = "refunded"
    TRIAL = "trial"


class PaymentStatus(Enum):
    """وضعیت پرداخت"""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class SubscriptionType(Enum):
    """نوع اشتراک"""

    NEW = "new"
    RENEWAL = "renewal"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"


def generate_secure_uuid() -> str:
    """تولید UUID امن"""

    return str(uuid.uuid4())


class UserSubscription(Base):
    """مدل کامل اشتراک کاربر"""

    __tablename__ = "user_subscriptions"

    id = Column(String(36), primary_key=True, default=generate_secure_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(String(36), ForeignKey("subscription_plans.id"), nullable=False)

    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False)
    subscription_type = Column(SQLEnum(SubscriptionType), default=SubscriptionType.NEW, nullable=False)

    start_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    end_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    activated_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    is_trial = Column(Boolean, default=False)
    trial_end_date = Column(DateTime)
    grace_period_end = Column(DateTime)

    payment_status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    amount_paid = Column(Numeric(10, 2), default=0.00)
    currency = Column(String(3), default="USD")
    payment_method = Column(String(50))
    transaction_id = Column(String(100))
    payment_gateway = Column(String(50))

    auto_renewal = Column(Boolean, default=True)
    renewal_attempts = Column(Integer, default=0)
    last_renewal_attempt = Column(DateTime)
    next_billing_date = Column(DateTime)

    previous_subscription_id = Column(String(36), ForeignKey("user_subscriptions.id"))
    upgrade_credit = Column(Numeric(10, 2), default=0.00)

    reminder_sent = Column(Boolean, default=False)
    reminder_sent_at = Column(DateTime)
    expiry_notification_sent = Column(Boolean, default=False)
    renewal_notification_sent = Column(Boolean, default=False)

    usage_limit_storage_mb = Column(Integer)
    usage_limit_files = Column(Integer)
    current_storage_used = Column(Integer, default=0)
    current_files_count = Column(Integer, default=0)

    metadata = Column(Text)
    admin_notes = Column(Text)
    cancellation_reason = Column(Text)
    refund_reason = Column(Text)

    discount_code = Column(String(50))
    discount_amount = Column(Numeric(10, 2), default=0.00)
    promotional_credits = Column(Numeric(10, 2), default=0.00)

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    previous_subscription = relationship("UserSubscription", remote_side=[id], backref="upgraded_to")

    __table_args__ = (
        CheckConstraint("end_date > start_date", name="valid_date_range"),
        CheckConstraint("amount_paid >= 0", name="non_negative_amount"),
        CheckConstraint("renewal_attempts >= 0", name="non_negative_attempts"),
        CheckConstraint("current_storage_used >= 0", name="non_negative_storage"),
        CheckConstraint("current_files_count >= 0", name="non_negative_files"),
        CheckConstraint("trial_end_date IS NULL OR trial_end_date >= start_date", name="valid_trial_end"),
        UniqueConstraint("user_id", "status", name="unique_active_subscription", deferrable=True),
        Index("idx_user_subscriptions_user_id", "user_id"),
        Index("idx_user_subscriptions_status", "status"),
        Index("idx_user_subscriptions_plan_id", "plan_id"),
        Index("idx_user_subscriptions_end_date", "end_date"),
        Index("idx_user_subscriptions_user_status", "user_id", "status"),
        Index("idx_user_subscriptions_auto_renewal", "auto_renewal"),
        Index("idx_user_subscriptions_trial", "is_trial"),
        Index("idx_user_subscriptions_payment_status", "payment_status"),
        Index("idx_user_subscriptions_next_billing", "next_billing_date"),
        Index("idx_user_subscriptions_deleted", "deleted_at"),
    )

    @validates("end_date")
    def validate_end_date(self, key: str, value: datetime) -> datetime:
        if value and self.start_date and value <= self.start_date:
            raise ValidationError("end_date", value, "تاریخ پایان باید بعد از تاریخ شروع باشد")
        return value

    @validates("amount_paid")
    def validate_amount(self, key: str, value: Decimal) -> Decimal:
        if value < 0:
            raise ValidationError("amount_paid", value, "مبلغ نمی‌تواند منفی باشد")
        return Decimal(str(value)) if value else Decimal("0.00")

    @validates("user_id", "plan_id")
    def validate_foreign_keys(self, key: str, value: str) -> str:
        if not value:
            raise ValidationError(key, value, f"{key} الزامی است")
        return value

    @hybrid_property
    def is_active(self) -> bool:
        return (
            self.status == SubscriptionStatus.ACTIVE
            and self.end_date > datetime.utcnow()
            and not self.is_deleted
        )

    @hybrid_property
    def is_expired(self) -> bool:
        return self.end_date <= datetime.utcnow() or self.status == SubscriptionStatus.EXPIRED

    @hybrid_property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @hybrid_property
    def days_remaining(self) -> int:
        if self.is_expired:
            return 0
        return max(0, (self.end_date - datetime.utcnow()).days)

    @hybrid_property
    def hours_remaining(self) -> int:
        if self.is_expired:
            return 0
        delta = self.end_date - datetime.utcnow()
        return max(0, int(delta.total_seconds() / 3600))

    @hybrid_property
    def is_in_grace_period(self) -> bool:
        return self.grace_period_end is not None and datetime.utcnow() <= self.grace_period_end

    @hybrid_property
    def is_trial_active(self) -> bool:
        return self.is_trial and self.trial_end_date and datetime.utcnow() <= self.trial_end_date

    @hybrid_property
    def storage_usage_percentage(self) -> float:
        if not self.usage_limit_storage_mb:
            return 0
        return min(100, (self.current_storage_used / self.usage_limit_storage_mb) * 100)

    @hybrid_property
    def files_usage_percentage(self) -> float:
        if not self.usage_limit_files:
            return 0
        return min(100, (self.current_files_count / self.usage_limit_files) * 100)

    @hybrid_property
    def needs_renewal_reminder(self) -> bool:
        if self.reminder_sent or not self.is_active:
            return False
        return self.days_remaining <= 7

    def get_metadata(self) -> Dict[str, Any]:
        if not self.metadata:
            return {}
        try:
            import json

            return json.loads(self.metadata)
        except Exception:
            return {}

    def set_metadata(self, metadata: Dict[str, Any]) -> None:
        import json

        self.metadata = json.dumps(metadata, ensure_ascii=False)

    def add_metadata(self, key: str, value: Any) -> None:
        metadata = self.get_metadata()
        metadata[key] = value
        self.set_metadata(metadata)

    def activate_subscription(self) -> None:
        self.status = SubscriptionStatus.ACTIVE
        self.activated_at = datetime.utcnow()
        self.payment_status = PaymentStatus.COMPLETED
        if self.plan:
            self.usage_limit_storage_mb = self.plan.max_storage_mb
            self.usage_limit_files = self.plan.max_files
        if self.auto_renewal:
            self.next_billing_date = self.end_date

    def cancel_subscription(self, reason: str | None = None, immediate: bool = False) -> None:
        self.status = SubscriptionStatus.CANCELLED
        self.cancelled_at = datetime.utcnow()
        self.auto_renewal = False
        self.cancellation_reason = reason
        if immediate:
            self.end_date = datetime.utcnow()

    def suspend_subscription(self, reason: str | None = None) -> None:
        self.status = SubscriptionStatus.SUSPENDED
        self.suspended_at = datetime.utcnow()
        self.admin_notes = f"Suspended: {reason}" if reason else "Suspended"

    def expire_subscription(self) -> None:
        self.status = SubscriptionStatus.EXPIRED
        self.grace_period_end = datetime.utcnow() + timedelta(days=3)

    def extend_subscription(self, days: int) -> None:
        self.end_date = self.end_date + timedelta(days=days)
        if self.status == SubscriptionStatus.EXPIRED:
            self.status = SubscriptionStatus.ACTIVE

    def calculate_refund_amount(self) -> Decimal:
        if not self.is_active:
            return Decimal("0.00")
        total_days = (self.end_date - self.start_date).days
        remaining_days = self.days_remaining
        if total_days <= 0:
            return Decimal("0.00")
        daily_rate = self.amount_paid / total_days
        return daily_rate * remaining_days

    def process_refund(self, amount: Decimal | None = None, reason: str | None = None) -> None:
        refund_amount = amount or self.calculate_refund_amount()
        self.status = SubscriptionStatus.REFUNDED
        self.payment_status = PaymentStatus.REFUNDED
        self.refund_reason = reason
        self.cancelled_at = datetime.utcnow()
        self.add_metadata("refund_amount", float(refund_amount))
        self.add_metadata("refund_date", datetime.utcnow().isoformat())

    def upgrade_to_plan(self, new_plan_id: str, amount_paid: Decimal | None = None) -> "UserSubscription":
        remaining_value = self.calculate_refund_amount()
        self.cancel_subscription("Upgraded to new plan", immediate=True)
        new_subscription = UserSubscription(
            user_id=self.user_id,
            plan_id=new_plan_id,
            subscription_type=SubscriptionType.UPGRADE,
            previous_subscription_id=self.id,
            upgrade_credit=remaining_value,
            amount_paid=amount_paid or Decimal("0.00"),
        )
        return new_subscription

    def mark_as_deleted(self) -> None:
        self.deleted_at = datetime.utcnow()
        self.status = SubscriptionStatus.CANCELLED

    def restore(self) -> None:
        self.deleted_at = None
        if datetime.utcnow() <= self.end_date:
            self.status = SubscriptionStatus.ACTIVE
        else:
            self.status = SubscriptionStatus.EXPIRED

    def update_usage_stats(self, storage_mb: int, files_count: int) -> None:
        self.current_storage_used = max(0, storage_mb)
        self.current_files_count = max(0, files_count)
        self.updated_at = datetime.utcnow()

    def check_usage_limits(self) -> Dict[str, bool]:
        return {
            "storage_exceeded": self.usage_limit_storage_mb and self.current_storage_used > self.usage_limit_storage_mb,
            "files_exceeded": self.usage_limit_files and self.current_files_count > self.usage_limit_files,
        }

    def send_reminder(self) -> None:
        self.reminder_sent = True
        self.reminder_sent_at = datetime.utcnow()

    @classmethod
    def get_active_subscription(cls, session, user_id: str) -> "UserSubscription | None":
        return (
            session.query(cls)
            .filter(
                cls.user_id == user_id,
                cls.status == SubscriptionStatus.ACTIVE,
                cls.end_date > datetime.utcnow(),
                cls.deleted_at.is_(None),
            )
            .first()
        )

    @classmethod
    def get_expiring_subscriptions(cls, session, days_ahead: int = 7) -> list["UserSubscription"]:
        target_date = datetime.utcnow() + timedelta(days=days_ahead)
        return (
            session.query(cls)
            .filter(
                cls.status == SubscriptionStatus.ACTIVE,
                cls.end_date <= target_date,
                cls.end_date > datetime.utcnow(),
                cls.reminder_sent.is_(False),
                cls.deleted_at.is_(None),
            )
            .all()
        )

    @classmethod
    def get_subscription_history(cls, session, user_id: str) -> list["UserSubscription"]:
        return (
            session.query(cls)
            .filter(cls.user_id == user_id, cls.deleted_at.is_(None))
            .order_by(cls.created_at.desc())
            .all()
        )

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "plan_id": self.plan_id,
            "status": self.status.value,
            "subscription_type": self.subscription_type.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "is_active": self.is_active,
            "is_expired": self.is_expired,
            "days_remaining": self.days_remaining,
            "is_trial": self.is_trial,
            "auto_renewal": self.auto_renewal,
            "storage_usage_percentage": round(self.storage_usage_percentage, 1),
            "files_usage_percentage": round(self.files_usage_percentage, 1),
            "created_at": self.created_at.isoformat(),
        }
        if include_sensitive:
            data.update(
                {
                    "amount_paid": float(self.amount_paid),
                    "payment_status": self.payment_status.value,
                    "transaction_id": self.transaction_id,
                    "metadata": self.get_metadata(),
                    "admin_notes": self.admin_notes,
                }
            )
        return data

    def __repr__(self) -> str:
        return f"<UserSubscription(id='{self.id}', user_id='{self.user_id}', status='{self.status.value}')>"
