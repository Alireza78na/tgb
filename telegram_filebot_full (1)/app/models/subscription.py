from sqlalchemy import Column, String, Integer, Boolean, Numeric
from sqlalchemy.orm import relationship
from app.core.db import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    max_storage_mb = Column(Integer)
    max_files = Column(Integer)
    expiry_days = Column(Integer)
    price = Column(Numeric)
    is_active = Column(Boolean, default=True)

    users = relationship("User", back_populates="subscription")
