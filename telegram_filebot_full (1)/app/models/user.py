from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from app.core.db import Base
import uuid


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    full_name = Column(String)
    is_admin = Column(Boolean, default=False)
    is_blocked = Column(Boolean, default=False)
    block_reason = Column(String, nullable=True)
    block_type = Column(String, nullable=True)
    blocked_at = Column(DateTime, nullable=True)
    blocked_until = Column(DateTime, nullable=True)
    blocked_by = Column(String, nullable=True)
    unblocked_at = Column(DateTime, nullable=True)
    unblocked_by = Column(String, nullable=True)
    is_suspended = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)

    files = relationship("File", back_populates="user")
    subscriptions = relationship("UserSubscription", back_populates="user")
