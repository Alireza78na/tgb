from pydantic import BaseModel, ConfigDict, Field, validator
from typing import Optional
from datetime import datetime
import re

class FileCreate(BaseModel):
    original_file_name: str = Field(..., min_length=1, max_length=255)
    file_size: int = Field(..., gt=0, le=5 * 1024 * 1024 * 1024)
    is_from_link: Optional[bool] = False
    original_link: Optional[str] = None
    telegram_file_id: Optional[str] = None

    @validator("original_file_name")
    def validate_filename(cls, v: str) -> str:
        dangerous_chars = ["/", "\\", "..", "<", ">", ":", '"', "|", "?", "*"]
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"نام فایل نمی‌تواند شامل '{char}' باشد")

        if not re.match(r"^[^.]+\.[a-zA-Z0-9]+$", v):
            raise ValueError("نام فایل باید دارای پسوند معتبر باشد")
        return v.strip()

    @validator("original_link")
    def validate_link(cls, v: Optional[str], values):
        if values.get("is_from_link") and not v:
            raise ValueError("لینک الزامی است")
        if v and not re.match(r"^https?://", v):
            raise ValueError("لینک باید با http یا https شروع شود")
        return v

class FileLinkCreate(BaseModel):
    """Schema for creating a file from a remote URL."""
    url: str
    file_name: Optional[str] = None

class FileOut(BaseModel):
    id: str
    original_file_name: str
    file_size: int
    direct_download_url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
