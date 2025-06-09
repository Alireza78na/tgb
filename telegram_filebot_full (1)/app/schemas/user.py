from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    full_name: Optional[str] = None

class UserOut(BaseModel):
    id: str
    telegram_id: int
    username: Optional[str]
    full_name: Optional[str]
    is_admin: bool
    is_blocked: bool

    class Config:
        orm_mode = True
