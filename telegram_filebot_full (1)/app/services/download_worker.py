import requests
import os
from datetime import datetime
from uuid import uuid4

UPLOAD_DIR = "./uploads"

def download_file_from_url(url: str, filename: str) -> str:
    now = datetime.utcnow()
    date_path = now.strftime("%Y/%m/%d")
    folder_path = os.path.join(UPLOAD_DIR, date_path)
    os.makedirs(folder_path, exist_ok=True)

    unique_name = f"{uuid4().hex}_{filename}"
    full_path = os.path.join(folder_path, unique_name)

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        with open(full_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"[✔] File downloaded to: {full_path}")
        return full_path
    except Exception as e:
        print(f"[✘] Download failed: {e}")
        return ""
