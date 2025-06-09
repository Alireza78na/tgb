import requests
import os
from datetime import datetime
from uuid import uuid4
from typing import Callable, Optional
from app.core import config

UPLOAD_DIR = config.UPLOAD_DIR


def is_illegal_url(url: str) -> bool:
    url_lower = url.lower()
    return any(p in url_lower for p in config.ILLEGAL_PATTERNS)


def is_blocked_extension(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in config.BLOCKED_EXTENSIONS


def _prepare_path(filename: str) -> str:
    now = datetime.utcnow()
    date_path = now.strftime("%Y/%m/%d")
    folder_path = os.path.join(UPLOAD_DIR, date_path)
    os.makedirs(folder_path, exist_ok=True)
    unique_name = f"{uuid4().hex}_{filename}"
    return os.path.join(folder_path, unique_name)


def download_file_from_url(
    url: str,
    filename: str,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
) -> str:
    """Download a file with optional progress and cancellation."""
    if is_illegal_url(url) or is_blocked_extension(filename):
        print("[!] Download blocked due to illegal link or file type")
        return ""

    full_path = _prepare_path(filename)
    try:
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            with open(full_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if cancel_cb and cancel_cb():
                        print("[!] Download cancelled")
                        return ""
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total:
                            percent = int(downloaded * 100 / total)
                            progress_cb(percent)
        print(f"[✔] File downloaded to: {full_path}")
        return full_path
    except Exception as e:
        print(f"[✘] Download failed: {e}")
        return ""


def download_file_from_telegram(
    file_id: str,
    filename: str,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
) -> str:
    if is_blocked_extension(filename):
        print("[!] Download blocked due to disallowed file type")
        return ""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=15,
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        file_url = (
            f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_path}"
        )
        return download_file_from_url(
            file_url, filename, progress_cb=progress_cb, cancel_cb=cancel_cb
        )
    except Exception as e:
        print(f"[✘] Telegram download failed: {e}")
        return ""
