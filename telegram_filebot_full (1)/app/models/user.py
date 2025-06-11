from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    BigInteger,
    Text,
    JSON,
    Index,
    CheckConstraint,
    UniqueConstraint,
    Enum as SQLEnum,
    ForeignKey,
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List
import uuid
import re
import hashlib

from app.core.db import Base
from app.core.exceptions import ValidationError


class UserRole(Enum):
    """نقش کاربر"""

    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserStatus(Enum):
    """وضعیت کاربر"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    PENDING_VERIFICATION = "pending_verification"
    DELETED = "deleted"


class BlockType(Enum):
    """نوع مسدودیت"""

    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    SPAM = "spam"
    ABUSE = "abuse"
    MANUAL = "manual"
    AUTOMATED = "automated"


class Language(Enum):
    """زبان‌های پشتیبانی شده"""

    FA = "fa"
    EN = "en"
    AR = "ar"


def generate_secure_uuid() -> str:
    """تولید UUID امن"""

    return str(uuid.uuid4())


class User(Base):
    """مدل کامل کاربر برای ربات تلگرام"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_secure_uuid)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username = Column(String(50), index=True)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100))
    full_name = Column(String(200))
    display_name = Column(String(150))
    bio = Column(Text)

    phone_number = Column(String(20))
    email = Column(String(255))

    language_code = Column(SQLEnum(Language), default=Language.FA, nullable=False)
    timezone = Column(String(50), default="Asia/Tehran")

    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    permissions = Column(Text)

    status = Column(SQLEnum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)
    is_bot = Column(Boolean, default=False)

    is_blocked = Column(Boolean, default=False, nullable=False)
    block_type = Column(SQLEnum(BlockType))
    block_reason = Column(Text)
    blocked_at = Column(DateTime)
    blocked_until = Column(DateTime)
    blocked_by = Column(String(36), ForeignKey("users.id"))
    unblocked_at = Column(DateTime)
    unblocked_by = Column(String(36), ForeignKey("users.id"))

    password_hash = Column(String(128))
    api_key = Column(String(64), unique=True)
    two_factor_enabled = Column(Boolean, default=False)
    security_settings = Column(Text)

    last_activity_at = Column(DateTime)
    last_message_at = Column(DateTime)
    login_count = Column(Integer, default=0)
    message_count = Column(Integer, default=0)
    file_upload_count = Column(Integer, default=0)
    file_download_count = Column(Integer, default=0)

    user_settings = Column(Text)
    notification_settings = Column(Text)
    privacy_settings = Column(Text)

    referral_code = Column(String(20), unique=True)
    referred_by = Column(String(36), ForeignKey("users.id"))
    referral_count = Column(Integer, default=0)

    total_storage_used = Column(BigInteger, default=0)
    total_files_count = Column(Integer, default=0)
    total_downloads = Column(Integer, default=0)

    client_info = Column(Text)
    device_id = Column(String(100))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    files = relationship(
        "File",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    subscriptions = relationship(
        "UserSubscription",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    blocked_users = relationship(
        "User",
        foreign_keys=[blocked_by],
        remote_side=[id],
        backref="blocked_by_user",
    )
    referrer = relationship(
        "User",
        foreign_keys=[referred_by],
        remote_side=[id],
        backref="referred_users",
    )

    __table_args__ = (
        CheckConstraint("telegram_id > 0", name="positive_telegram_id"),
        CheckConstraint("login_count >= 0", name="non_negative_login_count"),
        CheckConstraint("message_count >= 0", name="non_negative_message_count"),
        CheckConstraint("file_upload_count >= 0", name="non_negative_upload_count"),
        CheckConstraint("total_storage_used >= 0", name="non_negative_storage"),
        CheckConstraint("referral_count >= 0", name="non_negative_referral_count"),
        UniqueConstraint("telegram_id", name="unique_telegram_id"),
        UniqueConstraint("api_key", name="unique_api_key"),
        UniqueConstraint("referral_code", name="unique_referral_code"),
        Index("idx_users_telegram_id", "telegram_id"),
        Index("idx_users_username", "telegram_username"),
        Index("idx_users_status", "status"),
        Index("idx_users_role", "role"),
        Index("idx_users_active", "is_active"),
        Index("idx_users_blocked", "is_blocked"),
        Index("idx_users_created_at", "created_at"),
        Index("idx_users_last_activity", "last_activity_at"),
        Index("idx_users_referral_code", "referral_code"),
        Index("idx_users_deleted_at", "deleted_at"),
        Index("idx_users_premium", "is_premium"),
        Index("idx_users_verified", "is_verified"),
    )

    @validates("telegram_id")
    def validate_telegram_id(self, key: str, telegram_id: int) -> int:
        if telegram_id <= 0:
            raise ValidationError("telegram_id", telegram_id, "شناسه تلگرام باید مثبت باشد")
        if telegram_id > 9999999999:
            raise ValidationError("telegram_id", telegram_id, "شناسه تلگرام نامعتبر است")
        return telegram_id

    @validates("telegram_username")
    def validate_username(self, key: str, username: Optional[str]) -> Optional[str]:
        if not username:
            return None
        username = username.lstrip("@").lower()
        if len(username) < 5 or len(username) > 32:
            raise ValidationError("username", username, "طول نام کاربری باید بین 5 تا 32 کاراکتر باشد")
        if not re.match(r"^[a-zA-Z0-9_]+$", username):
            raise ValidationError("username", username, "نام کاربری فقط می‌تواند شامل حروف، اعداد و _ باشد")
        return username

    @validates("first_name")
    def validate_first_name(self, key: str, name: str) -> str:
        if not name or len(name.strip()) == 0:
            raise ValidationError("first_name", name, "نام نمی‌تواند خالی باشد")
        if len(name) > 100:
            raise ValidationError("first_name", name, "نام بیش از حد طولانی است")
        return name.strip()

    @validates("email")
    def validate_email(self, key: str, email: Optional[str]) -> Optional[str]:
        if not email:
            return None
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, email):
            raise ValidationError("email", email, "فرمت ایمیل نامعتبر است")
        return email.lower()

    @validates("phone_number")
    def validate_phone(self, key: str, phone: Optional[str]) -> Optional[str]:
        if not phone:
            return None
        phone = re.sub(r"[^\d+]", "", phone)
        if not re.match(r"^\+?[1-9]\d{1,14}$", phone):
            raise ValidationError("phone_number", phone, "فرمت شماره تلفن نامعتبر است")
        return phone

    @hybrid_property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @hybrid_property
    def is_admin(self) -> bool:
        return self.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]

    @hybrid_property
    def is_moderator(self) -> bool:
        return self.role in [UserRole.MODERATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN]

    @hybrid_property
    def is_suspended(self) -> bool:
        return self.status == UserStatus.SUSPENDED

    @hybrid_property
    def full_name_display(self) -> str:
        if self.display_name:
            return self.display_name
        if self.full_name:
            return self.full_name
        return f"{self.first_name} {self.last_name or ''}".strip()

    @hybrid_property
    def storage_used_mb(self) -> float:
        return round(self.total_storage_used / (1024 * 1024), 2) if self.total_storage_used else 0

    @hybrid_property
    def is_temporarily_blocked(self) -> bool:
        return (
            self.is_blocked
            and self.block_type == BlockType.TEMPORARY
            and self.blocked_until
            and datetime.utcnow() < self.blocked_until
        )

    @hybrid_property
    def account_age_days(self) -> int:
        return (datetime.utcnow() - self.created_at).days

    def generate_referral_code(self) -> str:
        import secrets
        import string

        while True:
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            return f"REF{code}"

    def generate_api_key(self) -> str:
        import secrets

        self.api_key = secrets.token_urlsafe(32)
        return self.api_key

    def set_password(self, password: str) -> None:
        import bcrypt

        self.password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        import bcrypt

        return bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))

    def get_permissions(self) -> List[str]:
        if not self.permissions:
            return []
        try:
            import json

            return json.loads(self.permissions)
        except Exception:
            return []

    def set_permissions(self, permissions: List[str]) -> None:
        import json

        self.permissions = json.dumps(permissions)

    def has_permission(self, permission: str) -> bool:
        if self.is_admin:
            return True
        return permission in self.get_permissions()

    def add_permission(self, permission: str) -> None:
        permissions = self.get_permissions()
        if permission not in permissions:
            permissions.append(permission)
            self.set_permissions(permissions)

    def remove_permission(self, permission: str) -> None:
        permissions = self.get_permissions()
        if permission in permissions:
            permissions.remove(permission)
            self.set_permissions(permissions)

    def get_settings(self) -> Dict[str, Any]:
        if not self.user_settings:
            return {}
        try:
            import json

            return json.loads(self.user_settings)
        except Exception:
            return {}

    def set_settings(self, settings: Dict[str, Any]) -> None:
        import json

        self.user_settings = json.dumps(settings, ensure_ascii=False)

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.get_settings().get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        settings = self.get_settings()
        settings[key] = value
        self.set_settings(settings)

    def block_user(
        self,
        reason: str,
        block_type: BlockType = BlockType.MANUAL,
        duration_hours: Optional[int] = None,
        blocked_by_user_id: Optional[str] = None,
    ) -> None:
        self.is_blocked = True
        self.block_type = block_type
        self.block_reason = reason
        self.blocked_at = datetime.utcnow()
        self.blocked_by = blocked_by_user_id
        self.status = UserStatus.BLOCKED
        if duration_hours and block_type == BlockType.TEMPORARY:
            self.blocked_until = datetime.utcnow() + timedelta(hours=duration_hours)

    def unblock_user(self, unblocked_by_user_id: Optional[str] = None) -> None:
        self.is_blocked = False
        self.block_type = None
        self.block_reason = None
        self.blocked_at = None
        self.blocked_until = None
        self.unblocked_at = datetime.utcnow()
        self.unblocked_by = unblocked_by_user_id
        self.status = UserStatus.ACTIVE

    def suspend_user(self, reason: str) -> None:
        self.status = UserStatus.SUSPENDED
        self.block_reason = reason
        self.blocked_at = datetime.utcnow()

    def activate_user(self) -> None:
        self.status = UserStatus.ACTIVE
        self.is_active = True

    def mark_as_deleted(self) -> None:
        self.deleted_at = datetime.utcnow()
        self.status = UserStatus.DELETED
        self.is_active = False

    def restore(self) -> None:
        self.deleted_at = None
        self.status = UserStatus.ACTIVE
        self.is_active = True

    def update_activity(self) -> None:
        self.last_activity_at = datetime.utcnow()
        self.last_seen_at = datetime.utcnow()

    def increment_message_count(self) -> None:
        self.message_count = (self.message_count or 0) + 1
        self.last_message_at = datetime.utcnow()
        self.update_activity()

    def increment_login_count(self) -> None:
        self.login_count = (self.login_count or 0) + 1
        self.update_activity()

    def update_storage_stats(self, size_change: int = 0, file_count_change: int = 0) -> None:
        self.total_storage_used = max(0, (self.total_storage_used or 0) + size_change)
        self.total_files_count = max(0, (self.total_files_count or 0) + file_count_change)

    @classmethod
    def find_by_telegram_id(cls, session, telegram_id: int):
        return session.query(cls).filter(cls.telegram_id == telegram_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def find_by_username(cls, session, username: str):
        username = username.lstrip("@").lower()
        return session.query(cls).filter(cls.telegram_username == username, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_admins(cls, session):
        return (
            session.query(cls)
            .filter(
                cls.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]),
                cls.is_active.is_(True),
                cls.deleted_at.is_(None),
            )
            .all()
        )

    @classmethod
    def get_blocked_users(cls, session):
        return (
            session.query(cls)
            .filter(cls.is_blocked.is_(True), cls.deleted_at.is_(None))
            .all()
        )

    @classmethod
    def get_active_users_count(cls, session) -> int:
        return (
            session.query(cls)
            .filter(cls.is_active.is_(True), cls.deleted_at.is_(None))
            .count()
        )

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "telegram_username": self.telegram_username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name_display": self.full_name_display,
            "language_code": self.language_code.value,
            "role": self.role.value,
            "status": self.status.value,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "is_premium": self.is_premium,
            "is_blocked": self.is_blocked,
            "storage_used_mb": self.storage_used_mb,
            "total_files_count": self.total_files_count,
            "account_age_days": self.account_age_days,
            "created_at": self.created_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
        }
        if include_sensitive:
            data.update(
                {
                    "api_key": self.api_key,
                    "referral_code": self.referral_code,
                    "permissions": self.get_permissions(),
                    "settings": self.get_settings(),
                    "email": self.email,
                    "phone_number": self.phone_number,
                }
            )
        return data

    def __repr__(self) -> str:
        return f"<User(id='{self.id}', telegram_id={self.telegram_id}, name='{self.first_name}')>"
