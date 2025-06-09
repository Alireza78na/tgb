from sqlalchemy import Column, String, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.db import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class File(Base):
    __tablename__ = "files"
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"))
    original_file_name = Column(String)
    file_size = Column(Integer)
    storage_path = Column(Text)
    direct_download_url = Column(Text)
    download_token = Column(String, default=lambda: uuid.uuid4().hex)
    is_from_link = Column(Boolean, default=False)
    original_link = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="files")
