from pydantic import BaseModel, ConfigDict, Field, validator
from typing import Optional

class UserCreate(BaseModel):
    telegram_id: int = Field(..., gt=0)
    username: Optional[str] = Field(None, max_length=50)
    full_name: str = Field(..., min_length=1, max_length=100)

    @validator("telegram_id")
    def validate_telegram_id(cls, v):
        if v < 0 or v > 9999999999:
            raise ValueError("شناسه تلگرام نامعتبر است")
        return v

    @validator("username")
    def validate_username(cls, v):
        if v and not v.replace("_", "").isalnum():
            raise ValueError("نام کاربری فقط می‌تواند شامل حروف، اعداد و _ باشد")
        return v.lower() if v else v

    @validator("full_name")
    def validate_full_name(cls, v):
        if not v.strip():
            raise ValueError("نام کامل نمی‌تواند خالی باشد")
        return v.strip()

class UserOut(BaseModel):
    id: str
    telegram_id: int
    username: Optional[str]
    full_name: Optional[str]
    is_admin: bool
    is_blocked: bool

    model_config = ConfigDict(from_attributes=True)
