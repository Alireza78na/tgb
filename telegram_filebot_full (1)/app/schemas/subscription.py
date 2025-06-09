from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class UserSubscriptionCreate(BaseModel):
    user_id: str
    plan_id: str
    end_date: datetime

class UserSubscriptionOut(BaseModel):
    id: str
    user_id: str
    plan_id: str
    start_date: datetime
    end_date: datetime
    is_active: bool

    class Config:
        orm_mode = True


class SubscriptionPlanCreate(BaseModel):
    name: str
    max_storage_mb: Optional[int] = None
    max_files: Optional[int] = None
    expiry_days: Optional[int] = None
    price: Optional[float] = None
    is_active: bool = True


class SubscriptionPlanUpdate(SubscriptionPlanCreate):
    pass


class SubscriptionPlanOut(BaseModel):
    id: str
    name: str
    max_storage_mb: Optional[int]
    max_files: Optional[int]
    expiry_days: Optional[int]
    price: Optional[float]
    is_active: bool

    class Config:
        orm_mode = True
