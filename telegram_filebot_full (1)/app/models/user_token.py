from sqlalchemy import (
    Column, String, DateTime, Boolean, ForeignKey, Integer,
    Index, CheckConstraint, UniqueConstraint, Text, BigInteger,
    Enum as SQLEnum
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List
import uuid
import hashlib
import secrets
import ipaddress
from user_agents import parse

from app.core.db import Base
from app.core.exceptions import ValidationError


class TokenType(Enum):
    """نوع توکن"""

    ACCESS = "access"
    REFRESH = "refresh"
    API = "api"
    TEMPORARY = "temporary"
    ADMIN = "admin"


class TokenStatus(Enum):
    """وضعیت توکن"""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUSPENDED = "suspended"


class DeviceType(Enum):
    """نوع دستگاه"""

    MOBILE = "mobile"
    DESKTOP = "desktop"
    WEB = "web"
    BOT = "bot"
    API_CLIENT = "api_client"
    UNKNOWN = "unknown"


def generate_secure_uuid():
    """تولید UUID امن"""

    return str(uuid.uuid4())


def generate_secure_token():
    """تولید توکن امن"""

    return secrets.token_urlsafe(32)


class UserToken(Base):
    """مدل پیشرفته توکن کاربر با امکانات امنیتی"""

    __tablename__ = "user_tokens"

    # Primary fields
    id = Column(String(36), primary_key=True, default=generate_secure_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Token information
    token_hash = Column(String(64), nullable=False, index=True)
    token_type = Column(SQLEnum(TokenType), default=TokenType.ACCESS, nullable=False)
    status = Column(SQLEnum(TokenStatus), default=TokenStatus.ACTIVE, nullable=False)

    # Dates and expiration
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_used = Column(DateTime)
    revoked_at = Column(DateTime)

    # Device and client information
    device_info = Column(Text)
    device_type = Column(SQLEnum(DeviceType), default=DeviceType.UNKNOWN)
    device_id = Column(String(100))
    user_agent = Column(String(500))
    client_ip = Column(String(45))
    client_version = Column(String(50))

    # Security fields
    is_active = Column(Boolean, default=True, nullable=False)
    access_count = Column(Integer, default=0)
    max_uses = Column(Integer)
    scopes = Column(Text)

    # Geolocation (optional)
    country_code = Column(String(2))
    city = Column(String(100))
    latitude = Column(String(20))
    longitude = Column(String(20))

    # Security flags
    is_suspicious = Column(Boolean, default=False)
    security_score = Column(Integer, default=100)

    # Metadata
    metadata = Column(Text)
    revocation_reason = Column(String(200))

    # Relationships
    user = relationship("User", backref="tokens")

    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint('expires_at > created_at', name='valid_expiry_date'),
        CheckConstraint('access_count >= 0', name='non_negative_access_count'),
        CheckConstraint('security_score >= 0 AND security_score <= 100', name='valid_security_score'),
        CheckConstraint('max_uses IS NULL OR max_uses > 0', name='positive_max_uses'),
        UniqueConstraint('token_hash', name='unique_token_hash'),
        Index('idx_user_tokens_user_id', 'user_id'),
        Index('idx_user_tokens_expires_at', 'expires_at'),
        Index('idx_user_tokens_status', 'status'),
        Index('idx_user_tokens_type', 'token_type'),
        Index('idx_user_tokens_active', 'is_active'),
        Index('idx_user_tokens_user_active', 'user_id', 'is_active'),
        Index('idx_user_tokens_user_type', 'user_id', 'token_type'),
        Index('idx_user_tokens_device_id', 'device_id'),
        Index('idx_user_tokens_client_ip', 'client_ip'),
        Index('idx_user_tokens_suspicious', 'is_suspicious'),
        Index('idx_user_tokens_last_used', 'last_used'),
    )

    @validates('token_hash')
    def validate_token_hash(self, key, token_hash):
        """اعتبارسنجی hash توکن"""

        if not token_hash:
            raise ValidationError("token_hash", token_hash, "hash توکن الزامی است")
        if len(token_hash) != 64:
            raise ValidationError("token_hash", token_hash, "hash توکن باید 64 کاراکتر باشد")
        try:
            int(token_hash, 16)
        except ValueError:
            raise ValidationError("token_hash", token_hash, "فرمت hash نامعتبر است")
        return token_hash.lower()

    @validates('client_ip')
    def validate_ip_address(self, key, ip):
        """اعتبارسنجی آدرس IP"""

        if not ip:
            return None
        try:
            ipaddress.ip_address(ip)
            return ip
        except ValueError:
            raise ValidationError("client_ip", ip, "آدرس IP نامعتبر است")

    @validates('expires_at')
    def validate_expiry(self, key, expires_at):
        """اعتبارسنجی تاریخ انقضا"""

        if expires_at <= datetime.utcnow():
            raise ValidationError("expires_at", expires_at, "تاریخ انقضا باید در آینده باشد")
        max_expiry = datetime.utcnow() + timedelta(days=365)
        if expires_at > max_expiry:
            raise ValidationError("expires_at", expires_at, "مدت اعتبار توکن بیش از حد مجاز است")
        return expires_at

    @validates('user_agent')
    def validate_user_agent(self, key, user_agent):
        """اعتبارسنجی User-Agent"""

        if not user_agent:
            return None
        if len(user_agent) > 500:
            return user_agent[:500]
        if user_agent and not self.device_type:
            self.device_type = self._detect_device_type(user_agent)
        return user_agent

    @hybrid_property
    def is_expired(self):
        """بررسی انقضای توکن"""

        return datetime.utcnow() > self.expires_at

    @hybrid_property
    def is_valid(self):
        """بررسی معتبر بودن توکن"""

        return (
            self.is_active and not self.is_expired and self.status == TokenStatus.ACTIVE and not self.is_usage_exceeded
        )

    @hybrid_property
    def is_usage_exceeded(self):
        """بررسی تجاوز از حد استفاده"""

        return self.max_uses and self.access_count >= self.max_uses

    @hybrid_property
    def time_remaining(self):
        """زمان باقی‌مانده تا انقضا"""

        if self.is_expired:
            return timedelta(0)
        return self.expires_at - datetime.utcnow()

    @hybrid_property
    def hours_remaining(self):
        """ساعات باقی‌مانده"""

        return int(self.time_remaining.total_seconds() / 3600)

    @hybrid_property
    def is_recently_used(self):
        """بررسی استفاده اخیر"""

        if not self.last_used:
            return False
        return datetime.utcnow() - self.last_used < timedelta(hours=1)

    def _detect_device_type(self, user_agent: str) -> DeviceType:
        """تشخیص نوع دستگاه از User-Agent"""

        try:
            parsed = parse(user_agent)
            if parsed.is_mobile:
                return DeviceType.MOBILE
            elif parsed.is_pc:
                return DeviceType.DESKTOP
            elif 'bot' in user_agent.lower():
                return DeviceType.BOT
            else:
                return DeviceType.WEB
        except Exception:
            return DeviceType.UNKNOWN

    @classmethod
    def create_token(
        cls,
        user_id: str,
        token_type: TokenType = TokenType.ACCESS,
        expires_in_hours: int = 24,
        device_info: Optional[Dict] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ):
        """ایجاد توکن جدید"""

        raw_token = generate_secure_token()
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
        token = cls(
            user_id=user_id,
            token_hash=token_hash,
            token_type=token_type,
            expires_at=expires_at,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        if device_info:
            token.set_device_info(device_info)
        if scopes:
            token.set_scopes(scopes)
        return token, raw_token

    @classmethod
    def find_by_hash(cls, session, token_hash: str):
        """جستجو بر اساس hash توکن"""

        return (
            session.query(cls)
            .filter(cls.token_hash == token_hash, cls.is_active == True, cls.status == TokenStatus.ACTIVE)
            .first()
        )

    @classmethod
    def verify_token(cls, session, raw_token: str) -> Optional['UserToken']:
        """تایید توکن و بازگردان instance"""

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token = cls.find_by_hash(session, token_hash)
        if token and token.is_valid:
            token.mark_as_used()
            return token
        return None

    def mark_as_used(self):
        """علامت‌گذاری به عنوان استفاده شده"""

        self.last_used = datetime.utcnow()
        self.access_count += 1
        if self.is_usage_exceeded:
            self.revoke("Usage limit exceeded")

    def revoke(self, reason: str = None):
        """لغو توکن"""

        self.is_active = False
        self.status = TokenStatus.REVOKED
        self.revoked_at = datetime.utcnow()
        self.revocation_reason = reason

    def suspend(self, reason: str = None):
        """تعلیق موقت توکن"""

        self.status = TokenStatus.SUSPENDED
        self.revocation_reason = reason

    def reactivate(self):
        """فعال‌سازی مجدد توکن"""

        if not self.is_expired:
            self.status = TokenStatus.ACTIVE
            self.revocation_reason = None

    def extend_expiry(self, hours: int):
        """تمدید اعتبار توکن"""

        new_expiry = self.expires_at + timedelta(hours=hours)
        max_expiry = datetime.utcnow() + timedelta(days=365)
        if new_expiry <= max_expiry:
            self.expires_at = new_expiry
        else:
            raise ValidationError("expiry_extension", hours, "مدت تمدید بیش از حد مجاز است")

    def get_device_info(self) -> Dict[str, Any]:
        """دریافت اطلاعات دستگاه"""

        if not self.device_info:
            return {}
        try:
            import json

            return json.loads(self.device_info)
        except Exception:
            return {}

    def set_device_info(self, device_info: Dict[str, Any]):
        """تنظیم اطلاعات دستگاه"""

        import json
        device_info['recorded_at'] = datetime.utcnow().isoformat()
        self.device_info = json.dumps(device_info, ensure_ascii=False)
        if 'platform' in device_info:
            platform = device_info['platform'].lower()
            if 'mobile' in platform or 'android' in platform or 'ios' in platform:
                self.device_type = DeviceType.MOBILE
            elif 'windows' in platform or 'mac' in platform or 'linux' in platform:
                self.device_type = DeviceType.DESKTOP

    def get_scopes(self) -> List[str]:
        """دریافت مجوزهای توکن"""

        if not self.scopes:
            return []
        try:
            import json

            return json.loads(self.scopes)
        except Exception:
            return []

    def set_scopes(self, scopes: List[str]):
        """تنظیم مجوزهای توکن"""

        import json
        self.scopes = json.dumps(scopes)

    def has_scope(self, scope: str) -> bool:
        """بررسی داشتن مجوز خاص"""

        return scope in self.get_scopes()

    def add_scope(self, scope: str):
        """افزودن مجوز"""

        scopes = self.get_scopes()
        if scope not in scopes:
            scopes.append(scope)
            self.set_scopes(scopes)

    def calculate_security_score(self):
        """محاسبه امتیاز امنیتی"""

        score = 100
        age_days = (datetime.utcnow() - self.created_at).days
        if age_days > 30:
            score -= min(20, age_days - 30)
        if self.access_count > 1000:
            score -= min(15, (self.access_count - 1000) // 100)
        if self.is_suspicious:
            score -= 30
        if self.last_used and (datetime.utcnow() - self.last_used).days > 7:
            score -= 10
        self.security_score = max(0, min(100, score))
        return self.security_score

    def mark_as_suspicious(self, reason: str = None):
        """علامت‌گذاری به عنوان مشکوک"""

        self.is_suspicious = True
        self.calculate_security_score()
        if reason:
            metadata = self.get_metadata()
            metadata['suspicious_reason'] = reason
            metadata['marked_suspicious_at'] = datetime.utcnow().isoformat()
            self.set_metadata(metadata)

    def get_metadata(self) -> Dict[str, Any]:
        """دریافت metadata"""

        if not self.metadata:
            return {}
        try:
            import json

            return json.loads(self.metadata)
        except Exception:
            return {}

    def set_metadata(self, metadata: Dict[str, Any]):
        """تنظیم metadata"""

        import json
        self.metadata = json.dumps(metadata, ensure_ascii=False)

    @classmethod
    def cleanup_expired_tokens(cls, session, days_old: int = 30):
        """پاکسازی توکن‌های منقضی شده"""

        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        expired_tokens = session.query(cls).filter(cls.expires_at < cutoff_date).all()
        for token in expired_tokens:
            session.delete(token)
        return len(expired_tokens)

    @classmethod
    def get_user_active_tokens(cls, session, user_id: str):
        """دریافت توکن‌های فعال کاربر"""

        return (
            session.query(cls)
            .filter(
                cls.user_id == user_id,
                cls.is_active == True,
                cls.status == TokenStatus.ACTIVE,
                cls.expires_at > datetime.utcnow(),
            )
            .order_by(cls.last_used.desc())
            .all()
        )

    @classmethod
    def revoke_user_tokens(cls, session, user_id: str, except_token_id: str = None):
        """لغو تمام توکن‌های کاربر"""

        query = session.query(cls).filter(cls.user_id == user_id, cls.is_active == True)
        if except_token_id:
            query = query.filter(cls.id != except_token_id)
        tokens = query.all()
        for token in tokens:
            token.revoke("Revoked by user or admin")
        return len(tokens)

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """تبدیل به dictionary"""

        data = {
            'id': self.id,
            'token_type': self.token_type.value,
            'status': self.status.value,
            'device_type': self.device_type.value if self.device_type else None,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'is_valid': self.is_valid,
            'hours_remaining': self.hours_remaining,
            'access_count': self.access_count,
            'security_score': self.security_score,
            'is_suspicious': self.is_suspicious,
            'scopes': self.get_scopes(),
        }
        if include_sensitive:
            data.update({
                'token_hash': self.token_hash,
                'client_ip': self.client_ip,
                'user_agent': self.user_agent,
                'device_info': self.get_device_info(),
                'metadata': self.get_metadata(),
            })
        return data

    def __repr__(self):
        return f"<UserToken(id='{self.id}', user_id='{self.user_id}', type='{self.token_type.value}')>"
