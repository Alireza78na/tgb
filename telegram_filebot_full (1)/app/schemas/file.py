from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class FileCreate(BaseModel):
    original_file_name: str
    file_size: int
    is_from_link: Optional[bool] = False
    original_link: Optional[str] = None

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

    class Config:
        orm_mode = True
