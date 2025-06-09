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
