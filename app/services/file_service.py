import os
from datetime import datetime
from uuid import uuid4

UPLOAD_DIR = "./uploads"

def save_file_metadata(filename: str) -> str:
    now = datetime.utcnow()
    date_path = now.strftime("%Y/%m/%d")
    folder_path = os.path.join(UPLOAD_DIR, date_path)
    os.makedirs(folder_path, exist_ok=True)
    unique_name = f"{uuid4().hex}_{filename}"
    return os.path.join(folder_path, unique_name)
