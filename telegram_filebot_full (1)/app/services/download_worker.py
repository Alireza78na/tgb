import aiohttp
import aiofiles
import logging
from datetime import datetime
from uuid import uuid4
from typing import Optional, Callable, Dict, Any, Tuple
from pathlib import Path
import hashlib
import mimetypes
from urllib.parse import urlparse, unquote
import ipaddress
import os
import re
import ssl
import certifi
from dataclasses import dataclass
from enum import Enum

from app.core import config
from app.core.exceptions import FileOperationError, ValidationError


logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a security validation fails."""
    pass


class DownloadStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class SecurityLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    STRICT = "strict"


@dataclass
class DownloadProgress:
    total_size: int = 0
    downloaded: int = 0
    speed: float = 0.0
    eta: Optional[int] = None
    status: DownloadStatus = DownloadStatus.PENDING

    @property
    def percentage(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return min(100.0, (self.downloaded / self.total_size) * 100)


@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[str] = None
    file_size: int = 0
    duration: float = 0.0
    error: Optional[str] = None
    hash_md5: Optional[str] = None
    hash_sha256: Optional[str] = None
    mime_type: Optional[str] = None


class SecurityValidator:
    BLOCKED_EXTENSIONS = set(config.BLOCKED_EXTENSIONS)
    MALICIOUS_PATTERNS = ["malware", "virus", "trojan", "keylogger", "ransomware"]
    BLOCKED_DOMAINS = {"localhost", "127.0.0.1", "0.0.0.0"}

    @classmethod
    def is_safe_url(cls, url: str, level: SecurityLevel = SecurityLevel.MEDIUM) -> Tuple[bool, str]:
        try:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                return False, "invalid protocol"
            if not parsed.hostname:
                return False, "missing hostname"
            host = parsed.hostname.lower()
            if host in cls.BLOCKED_DOMAINS:
                return False, "blocked domain"
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback:
                    return False, "private ip"
            except ValueError:
                pass
            url_lower = url.lower()
            for pat in config.ILLEGAL_PATTERNS:
                if pat in url_lower:
                    return False, "illegal pattern"
            for pat in cls.MALICIOUS_PATTERNS:
                if pat in url_lower:
                    return False, f"malicious pattern {pat}"
            if level in [SecurityLevel.HIGH, SecurityLevel.STRICT]:
                if len(url) > 2048:
                    return False, "url too long"
            return True, "ok"
        except Exception as e:
            return False, f"error {e}"

    @classmethod
    def is_safe_filename(cls, filename: str) -> Tuple[bool, str]:
        if not filename or not filename.strip():
            return False, "empty filename"
        if len(filename) > 255:
            return False, "filename too long"
        dangerous = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*', '\0']
        for c in dangerous:
            if c in filename:
                return False, f"dangerous char {c}"
        _, ext = os.path.splitext(filename)
        if ext.lower() in cls.BLOCKED_EXTENSIONS:
            return False, f"blocked extension {ext}"
        return True, "ok"


class AdvancedDownloadWorker:
    def __init__(self) -> None:
        self.cfg = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.security_level = SecurityLevel.MEDIUM
        self.max_file_size = getattr(self.cfg, "max_file_size_bytes", 2 * 1024 * 1024 * 1024)
        self.chunk_size = 8192
        self.timeout = aiohttp.ClientTimeout(total=300, connect=30)
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        self.ssl_context = ctx

    async def __aenter__(self) -> "AdvancedDownloadWorker":
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=10, ssl=self.ssl_context)
        self.session = aiohttp.ClientSession(connector=connector, timeout=self.timeout,
                                             headers={"User-Agent": "TelegramFileBot/1.0"})
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.session:
            await self.session.close()

    async def get_remote_file_info(self, url: str) -> Dict[str, Any]:
        is_safe, reason = SecurityValidator.is_safe_url(url, self.security_level)
        if not is_safe:
            raise SecurityError(f"Unsafe url: {reason}")
        assert self.session
        try:
            async with self.session.head(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise FileOperationError(f"HTTP {resp.status}: {resp.reason}")
                size = int(resp.headers.get("Content-Length", 0))
                if size and size > self.max_file_size:
                    raise ValidationError("file_size", size, "File too large")
                filename = self._extract_filename(resp, url)
                safe, reason = SecurityValidator.is_safe_filename(filename)
                if not safe:
                    raise SecurityError(f"Unsafe filename: {reason}")
                return {
                    "filename": filename,
                    "size": size,
                    "content_type": resp.headers.get("Content-Type"),
                    "url": str(resp.url),
                }
        except aiohttp.ClientError as e:
            raise FileOperationError(f"Head request failed: {e}")

    def _extract_filename(self, response: aiohttp.ClientResponse, url: str) -> str:
        disposition = response.headers.get("Content-Disposition", "")
        if "filename=" in disposition:
            match = re.search(r"filename\*?=([^;]+)", disposition)
            if match:
                return unquote(match.group(1).strip('"\''))
        parsed = urlparse(url)
        name = Path(unquote(parsed.path)).name
        if not Path(name).suffix and response.headers.get("Content-Type"):
            ctype = response.headers["Content-Type"].split(";")[0]
            ext = mimetypes.guess_extension(ctype)
            if ext:
                name += ext
        return name or "download"

    def _prepare_file_path(self, filename: str) -> Path:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
        now = datetime.utcnow()
        folder = Path(self.cfg.UPLOAD_DIR) / now.strftime("%Y/%m/%d")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{uuid4().hex}_{safe}"

    async def download_from_url(
        self,
        url: str,
        filename: Optional[str] = None,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> DownloadResult:
        start = datetime.utcnow()
        progress = DownloadProgress(status=DownloadStatus.PENDING)
        try:
            info = await self.get_remote_file_info(url)
            final_name = filename or info["filename"]
            path = self._prepare_file_path(final_name)
            progress.total_size = info["size"]
            progress.status = DownloadStatus.DOWNLOADING
            if progress_callback:
                progress_callback(progress)
            md5 = hashlib.md5()
            sha = hashlib.sha256()
            assert self.session
            async with self.session.get(url) as resp:
                resp.raise_for_status()
                async with aiofiles.open(path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(self.chunk_size):
                        if cancel_callback and cancel_callback():
                            progress.status = DownloadStatus.CANCELLED
                            if progress_callback:
                                progress_callback(progress)
                            try:
                                path.unlink()
                            except Exception:
                                pass
                            return DownloadResult(success=False, error="cancelled")
                        await f.write(chunk)
                        md5.update(chunk)
                        sha.update(chunk)
                        progress.downloaded += len(chunk)
                        if progress_callback and progress.total_size:
                            progress_callback(progress)
            progress.status = DownloadStatus.COMPLETED
            if progress_callback:
                progress_callback(progress)
            duration = (datetime.utcnow() - start).total_seconds()
            return DownloadResult(
                success=True,
                file_path=str(path),
                file_size=progress.downloaded,
                duration=duration,
                hash_md5=md5.hexdigest(),
                hash_sha256=sha.hexdigest(),
                mime_type=info.get("content_type"),
            )
        except Exception as e:
            progress.status = DownloadStatus.FAILED
            if progress_callback:
                progress_callback(progress)
            logger.error("Download error: %s", e, exc_info=True)
            return DownloadResult(success=False, error=str(e))

    async def download_from_telegram(
        self,
        file_id: str,
        filename: Optional[str] = None,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> DownloadResult:
        assert self.session
        try:
            info_url = f"https://api.telegram.org/bot{self.cfg.BOT_TOKEN}/getFile"
            async with self.session.get(info_url, params={"file_id": file_id}) as resp:
                resp.raise_for_status()
                result = await resp.json()
                if not result.get("ok"):
                    raise FileOperationError(f"Telegram API error: {result.get('description')}")
                file_data = result["result"]
                t_file_path = file_data["file_path"]
                download_url = f"https://api.telegram.org/file/bot{self.cfg.BOT_TOKEN}/{t_file_path}"
                if not filename:
                    filename = Path(t_file_path).name
                safe, reason = SecurityValidator.is_safe_filename(filename)
                if not safe:
                    raise SecurityError(f"Unsafe filename: {reason}")
                return await self.download_from_url(
                    download_url,
                    filename,
                    progress_callback,
                    cancel_callback,
                )
        except Exception as e:
            logger.error("Telegram download error: %s", e, exc_info=True)
            return DownloadResult(success=False, error=str(e))


_download_worker: Optional[AdvancedDownloadWorker] = None


async def get_download_worker() -> AdvancedDownloadWorker:
    global _download_worker
    if _download_worker is None:
        worker = AdvancedDownloadWorker()
        await worker.__aenter__()
        _download_worker = worker
    return _download_worker


async def download_file_from_url(
    url: str,
    filename: Optional[str] = None,
    progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
) -> DownloadResult:
    worker = await get_download_worker()
    return await worker.download_from_url(url, filename, progress_callback, cancel_callback)


async def download_file_from_telegram(
    file_id: str,
    filename: Optional[str] = None,
    progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
) -> DownloadResult:
    worker = await get_download_worker()
    return await worker.download_from_telegram(file_id, filename, progress_callback, cancel_callback)


async def get_remote_file_size(url: str) -> int:
    try:
        worker = await get_download_worker()
        info = await worker.get_remote_file_info(url)
        return info["size"]
    except Exception as e:
        logger.error("Failed to get remote file size: %s", e)
        return 0


async def cleanup_download_worker() -> None:
    global _download_worker
    if _download_worker:
        await _download_worker.__aexit__(None, None, None)
        _download_worker = None


# --- Task Queue Function ---
import uuid
from app.core.db import db_manager
from app.models.file import File
from app.core.subscription_guard import check_user_limits, check_active_subscription
from app.core.exceptions import SubscriptionLimitExceededError, SubscriptionExpiredError

async def process_download_from_url_task(
    user_id: str, url: str, filename: Optional[str] = None
) -> Dict[str, Any]:
    """
    Task function to download a file from a URL, save it, and create a DB record.
    This function is intended to be run by the AdvancedTaskQueue.
    """
    logger.info(f"Starting download task for user {user_id} from URL: {url}")
    worker = await get_download_worker()

    async with db_manager.get_session() as db:
        try:
            # 1. Check subscription and limits before starting the download
            info = await worker.get_remote_file_info(url)
            remote_size = info.get("size", 0)

            await check_active_subscription(user_id, db)
            await check_user_limits(user_id, remote_size, db)

            # 2. Perform the download
            result = await worker.download_from_url(url, filename)
            if not result.success or not result.file_path:
                raise FileOperationError(result.error or "Download failed")

            # 3. Create file record in the database
            file_id = str(uuid.uuid4())
            token = uuid.uuid4().hex
            direct_download_url = (
                f"https://{config.DOWNLOAD_DOMAIN}/api/file/download/{file_id}/{token}"
            )

            new_file = File(
                id=file_id,
                user_id=user_id,
                original_file_name=filename or Path(result.file_path).name,
                file_size=result.file_size,
                storage_path=result.file_path,
                direct_download_url=direct_download_url,
                download_token=token,
                is_from_link=True,
                original_link=url,
                created_at=datetime.utcnow(),
            )
            db.add(new_file)
            await db.commit()
            await db.refresh(new_file)

            logger.info(f"Successfully completed download task {new_file.id} for user {user_id}")

            return {
                "success": True,
                "file_id": new_file.id,
                "direct_download_url": new_file.direct_download_url,
            }

        except (SubscriptionLimitExceededError, SubscriptionExpiredError, SecurityError) as e:
            logger.warning(f"Download task failed for user {user_id} due to policy violation: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Unhandled error in download task for user {user_id}: {e}", exc_info=True)
            return {"success": False, "error": "An unexpected server error occurred."}
