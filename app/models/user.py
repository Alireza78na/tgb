from sqlalchemy import Column, String, Integer, Boolean
from sqlalchemy.orm import relationship
from app.core.db import Base
import uuid


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)

    files = relationship("File", back_populates="user")
    subscriptions = relationship("UserSubscription", back_populates="user")
