import json
import os
import asyncio
import threading
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime
import logging
from cryptography.fernet import Fernet
from pydantic import BaseModel, validator, Field
import aiofiles

logger = logging.getLogger(__name__)


class SettingsSchema(BaseModel):
    """Schema for validating settings"""

    BOT_TOKEN: str = Field(..., min_length=10)
    DOWNLOAD_DOMAIN: str = Field(default="localhost")
    API_ID: int = Field(..., gt=0)
    API_HASH: str = Field(..., min_length=32)
    ADMIN_IDS: str = Field(default="")
    REQUIRED_CHANNEL: Optional[str] = None
    UPLOAD_DIR: str = Field(default="./uploads")
    SUBSCRIPTION_REMINDER_DAYS: int = Field(default=3, ge=1, le=30)
    MAX_FILE_SIZE_MB: int = Field(default=2048, ge=1, le=4096)
    RATE_LIMIT_PER_MINUTE: int = Field(default=60, ge=10, le=1000)

    @validator("BOT_TOKEN")
    def validate_bot_token(cls, v: str) -> str:  # noqa: D401
        if v in ["YOUR_BOT_TOKEN", ""]:
            raise ValueError("BOT_TOKEN باید تنظیم شود")
        if len(v) < 40 or ":" not in v:
            raise ValueError("فرمت BOT_TOKEN نامعتبر است")
        return v

    @validator("ADMIN_IDS")
    def validate_admin_ids(cls, v: str) -> str:  # noqa: D401
        if v:
            try:
                ids = [int(uid.strip()) for uid in v.split(",") if uid.strip()]
                return ",".join(map(str, ids))
            except ValueError as e:
                raise ValueError("فرمت ADMIN_IDS نامعتبر است") from e
        return v


class SecureSettingsManager:
    """Thread-safe and encrypted settings manager"""

    def __init__(self, settings_path: str | Path | None = None, encryption_key: bytes | str | None = None) -> None:
        self.settings_path = Path(settings_path or self._default_path())
        self.backup_dir = self.settings_path.parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()
        self.thread_lock = threading.RLock()
        self._cache: Optional[Dict[str, Any]] = None
        self._last_modified: Optional[float] = None

        if encryption_key:
            self.cipher = Fernet(encryption_key if isinstance(encryption_key, bytes) else encryption_key.encode())
        else:
            self.cipher = None

        self.sensitive_keys = {
            "BOT_TOKEN",
            "API_HASH",
            "SECRET_KEY",
            "DATABASE_URL",
        }

    def _default_path(self) -> str:
        return os.path.join(os.path.dirname(__file__), "..", "settings.json")

    def _generate_backup_name(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"settings_backup_{timestamp}.json"

    async def _create_backup(self) -> Path | None:
        if not self.settings_path.exists():
            return None
        backup_file = self.backup_dir / self._generate_backup_name()
        try:
            async with aiofiles.open(self.settings_path, "r") as src, aiofiles.open(backup_file, "w") as dst:
                await dst.write(await src.read())
            logger.info("Settings backup created: %s", backup_file)
            return backup_file
        except Exception as e:  # pragma: no cover - just log
            logger.error("Failed to create backup: %s", e)
            return None

    def _cleanup_backups(self, keep: int = 10) -> None:
        try:
            backups = sorted(self.backup_dir.glob("settings_backup_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
            for old in backups[keep:]:
                old.unlink(missing_ok=True)
                logger.info("Removed old backup: %s", old)
        except Exception as e:  # pragma: no cover
            logger.error("Error cleaning backups: %s", e)

    def _encrypt_value(self, key: str, value: Any) -> Any:
        if self.cipher and key in self.sensitive_keys and isinstance(value, str):
            try:
                encrypted = self.cipher.encrypt(value.encode()).decode()
                return {"_encrypted": encrypted}
            except Exception as e:  # pragma: no cover
                logger.warning("Failed to encrypt %s: %s", key, e)
        return value

    def _decrypt_value(self, key: str, value: Any) -> Any:
        if self.cipher and isinstance(value, dict) and "_encrypted" in value and key in self.sensitive_keys:
            try:
                decrypted = self.cipher.decrypt(value["_encrypted"].encode()).decode()
                return decrypted
            except Exception as e:  # pragma: no cover
                logger.warning("Failed to decrypt %s: %s", key, e)
        return value

    def _encrypt_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        return {k: self._encrypt_value(k, v) for k, v in settings.items()}

    def _decrypt_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        return {k: self._decrypt_value(k, v) for k, v in settings.items()}

    async def _file_changed(self) -> bool:
        try:
            if not self.settings_path.exists():
                return self._last_modified is not None
            current = self.settings_path.stat().st_mtime
            if self._last_modified is None or current != self._last_modified:
                self._last_modified = current
                return True
            return False
        except Exception:
            return True

    async def load(self, force_reload: bool = False) -> Dict[str, Any]:
        async with self.lock:
            if not force_reload and self._cache is not None and not await self._file_changed():
                return self._cache.copy()

            if not self.settings_path.exists():
                logger.info("Settings file not found, creating default")
                default_settings = await self._create_default_settings()
                await self.save(default_settings, create_backup=False)
                return default_settings

            try:
                async with aiofiles.open(self.settings_path, "r", encoding="utf-8") as f:
                    settings = json.loads(await f.read())
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON in settings file: %s", e)
                restored = await self._restore_from_backup()
                if restored:
                    return restored
                raise ValueError("تنظیمات نامعتبر و backup قابل دسترس نیست") from e

            settings = self._decrypt_settings(settings)

            try:
                SettingsSchema(**settings)
            except Exception as e:  # pragma: no cover - validation warnings
                logger.warning("Settings validation failed: %s", e)

            self._cache = settings
            return settings.copy()

    async def save(self, settings: Dict[str, Any], create_backup: bool = True) -> None:
        async with self.lock:
            SettingsSchema(**settings)
            if create_backup and self.settings_path.exists():
                await self._create_backup()
            encrypted = self._encrypt_settings(settings)
            tmp_path = self.settings_path.with_suffix(".tmp")
            try:
                async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(encrypted, indent=2, ensure_ascii=False))
                tmp_path.replace(self.settings_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            self._cache = settings.copy()
            if self.settings_path.exists():
                self._last_modified = self.settings_path.stat().st_mtime
            self._cleanup_backups()
            logger.info("Settings saved successfully")

    async def update(self, updates: Dict[str, Any], validate: bool = True) -> Dict[str, Any]:
        async with self.lock:
            current = await self.load()
            new_settings = {**current, **updates}
            if validate:
                SettingsSchema(**new_settings)
            await self.save(new_settings)
            logger.info("Settings updated: %s", list(updates.keys()))
            return new_settings

    async def get(self, key: str, default: Any = None) -> Any:
        settings = await self.load()
        return settings.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        await self.update({key: value})

    async def delete(self, key: str) -> None:
        settings = await self.load()
        if key in settings:
            del settings[key]
            await self.save(settings)
            logger.info("Setting deleted: %s", key)

    async def _create_default_settings(self) -> Dict[str, Any]:
        return {
            "BOT_TOKEN": "YOUR_BOT_TOKEN",
            "DOWNLOAD_DOMAIN": "localhost",
            "API_ID": 0,
            "API_HASH": "",
            "ADMIN_IDS": "",
            "REQUIRED_CHANNEL": None,
            "UPLOAD_DIR": "./uploads",
            "SUBSCRIPTION_REMINDER_DAYS": 3,
            "MAX_FILE_SIZE_MB": 2048,
            "RATE_LIMIT_PER_MINUTE": 60,
        }

    async def _restore_from_backup(self) -> Optional[Dict[str, Any]]:
        try:
            backups = list(self.backup_dir.glob("settings_backup_*.json"))
            if not backups:
                return None
            latest = max(backups, key=lambda x: x.stat().st_mtime)
            async with aiofiles.open(latest, "r") as f:
                settings = json.loads(await f.read())
            settings = self._decrypt_settings(settings)
            await self.save(settings, create_backup=False)
            logger.info("Settings restored from backup: %s", latest)
            return settings
        except Exception as e:  # pragma: no cover
            logger.error("Failed to restore from backup: %s", e)
            return None

    def get_sync(self, key: str, default: Any = None) -> Any:
        with self.thread_lock:
            try:
                if self.settings_path.exists():
                    with open(self.settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data = self._decrypt_settings(data)
                    return data.get(key, default)
            except Exception as e:  # pragma: no cover
                logger.error("Error in sync get: %s", e)
            return default

    async def export_settings(self, export_path: Path, include_sensitive: bool = False) -> None:
        settings = await self.load()
        if not include_sensitive:
            settings = {k: v for k, v in settings.items() if k not in self.sensitive_keys}
        async with aiofiles.open(export_path, "w") as f:
            await f.write(json.dumps(settings, indent=2, ensure_ascii=False))
        logger.info("Settings exported to: %s", export_path)

    async def import_settings(self, import_path: Path, merge: bool = True) -> None:
        async with aiofiles.open(import_path, "r") as f:
            imported = json.loads(await f.read())
        if merge:
            current = await self.load()
            current.update(imported)
            await self.save(current)
        else:
            await self.save(imported)
        logger.info("Settings imported from: %s", import_path)


encryption_key = os.getenv("SETTINGS_ENCRYPTION_KEY")
if not encryption_key:
    encryption_key = Fernet.generate_key()
    logger.warning(
        "No encryption key found, generated new key. Set SETTINGS_ENCRYPTION_KEY environment variable."
    )

settings_manager = SecureSettingsManager(encryption_key=encryption_key)


class SettingsManager:
    """Backward compatible wrapper"""

    @classmethod
    def load(cls) -> Dict[str, Any]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(settings_manager.load())
        finally:
            loop.close()

    @classmethod
    def save(cls, data: Dict[str, Any]) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(settings_manager.save(data))
        finally:
            loop.close()

    @classmethod
    def update(cls, updates: Dict[str, Any]) -> Dict[str, Any]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(settings_manager.update(updates))
        finally:
            loop.close()

