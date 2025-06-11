import os
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional, Set

from dotenv import load_dotenv
from pydantic import BaseSettings, Field, validator

from .settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class TelegramBotConfig(BaseSettings):
    """Advanced configuration for the Telegram bot."""

    BOT_TOKEN: str = Field(..., description="Telegram Bot Token")
    API_ID: int = Field(..., gt=0, description="Telegram API ID")
    API_HASH: str = Field(..., min_length=32, description="Telegram API Hash")

    DOWNLOAD_DOMAIN: str = Field("localhost", description="Download domain")
    UPLOAD_DIR: Path = Field(Path("./uploads"), description="Upload directory")
    MAX_FILE_SIZE_MB: int = Field(2048, ge=1, le=4096)

    ADMIN_IDS: str = Field("", description="Comma separated admin IDs")
    REQUIRED_CHANNEL: Optional[str] = None

    SUBSCRIPTION_REMINDER_DAYS: int = Field(3, ge=1, le=30)

    SECRET_KEY: str = Field(default_factory=lambda: os.urandom(32).hex())
    RATE_LIMIT_PER_MINUTE: int = Field(60, ge=10, le=1000)
    SESSION_EXPIRE_HOURS: int = Field(24, ge=1, le=168)

    DATABASE_URL: str = Field("sqlite+aiosqlite:///./filebot.db")
    DATABASE_ECHO: bool = Field(False)

    ENVIRONMENT: str = Field("production", regex="^(development|staging|production)$")
    DEBUG: bool = Field(False)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    @validator("BOT_TOKEN")
    def validate_bot_token(cls, v: str) -> str:
        if v == "YOUR_BOT_TOKEN" or len(v) < 40:
            raise ValueError("BOT_TOKEN نامعتبر است - از BotFather دریافت کنید")
        if v.count(":") != 1:
            raise ValueError("فرمت BOT_TOKEN اشتباه است")
        return v

    @validator("API_HASH")
    def validate_api_hash(cls, v: str) -> str:
        if len(v) != 32 or not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError("API_HASH نامعتبر است")
        return v.lower()

    @validator("DOWNLOAD_DOMAIN")
    def validate_domain(cls, v: str) -> str:
        if v.startswith(("http://", "https://")):
            return v
        return f"https://{v}"

    @validator("UPLOAD_DIR")
    def validate_upload_dir(cls, v: Path) -> Path:
        upload_path = Path(v)
        try:
            upload_path.mkdir(parents=True, exist_ok=True)
            test_file = upload_path / ".test_write"
            test_file.write_text("test")
            test_file.unlink()
            return upload_path
        except (OSError, PermissionError) as e:
            raise ValueError(f"دسترسی به پوشه آپلود ممکن نیست: {e}")

    @validator("ADMIN_IDS")
    def validate_admin_ids(cls, v: str) -> str:
        if not v.strip():
            logger.warning("هیچ ADMIN_ID تعریف نشده است")
            return v
        try:
            ids = [int(uid.strip()) for uid in v.split(",") if uid.strip()]
            for uid in ids:
                if uid <= 0 or uid > 9999999999:
                    raise ValueError(f"شناسه ادمین نامعتبر: {uid}")
            return ",".join(map(str, ids))
        except ValueError as e:
            raise ValueError(f"فرمت ADMIN_IDS اشتباه است: {e}")

    @property
    def admin_ids_set(self) -> Set[int]:
        if not self.ADMIN_IDS.strip():
            return set()
        return {int(uid.strip()) for uid in self.ADMIN_IDS.split(",") if uid.strip()}

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


class SecurityConfig:
    """Security related file configuration."""

    BLOCKED_EXTENSIONS = {
        ".exe",
        ".bat",
        ".cmd",
        ".sh",
        ".msi",
        ".dll",
        ".scr",
        ".ps1",
        ".com",
        ".pif",
        ".application",
        ".gadget",
        ".msp",
        ".msc",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".ws",
        ".wsf",
        ".wsc",
        ".wsh",
        ".xlsm",
        ".xltm",
        ".docm",
        ".dotm",
        ".pptm",
        ".potm",
        ".ppam",
        ".sys",
        ".drv",
        ".ocx",
        ".cpl",
        ".inf",
        ".reg",
    }

    ILLEGAL_PATTERNS = [
        "magnet:",
        ".torrent",
        "ed2k://",
        "thunder://",
        "javascript:",
        "data:",
        "vbscript:",
        "file://",
        r"\.exe\.",
        r"\.bat\.",
        r"\.cmd\.",
    ]

    MAX_FILE_SIZES = {
        "image": 50 * 1024 * 1024,
        "video": 2 * 1024 * 1024 * 1024,
        "audio": 100 * 1024 * 1024,
        "document": 500 * 1024 * 1024,
        "archive": 1024 * 1024 * 1024,
        "default": 100 * 1024 * 1024,
    }

    ALLOWED_MIME_TYPES = {
        "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
        "video": ["video/mp4", "video/avi", "video/mkv", "video/mov"],
        "audio": ["audio/mp3", "audio/wav", "audio/flac", "audio/ogg"],
        "document": ["application/pdf", "text/plain", "application/msword"],
        "archive": ["application/zip", "application/x-rar", "application/x-7z-compressed"],
    }

    @classmethod
    def is_blocked_extension(cls, filename: str) -> bool:
        filename_lower = filename.lower()
        for ext in cls.BLOCKED_EXTENSIONS:
            if filename_lower.endswith(ext):
                return True
        for pattern in cls.ILLEGAL_PATTERNS:
            if pattern.startswith('r"') and pattern.endswith('"'):
                import re
                if re.search(pattern[2:-1], filename_lower):
                    return True
            else:
                if pattern in filename_lower:
                    return True
        return False

    @classmethod
    def get_file_type(cls, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        video_exts = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv'}
        audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.aac', '.m4a'}
        doc_exts = {'.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
        archive_exts = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'}
        if ext in image_exts:
            return 'image'
        elif ext in video_exts:
            return 'video'
        elif ext in audio_exts:
            return 'audio'
        elif ext in doc_exts:
            return 'document'
        elif ext in archive_exts:
            return 'archive'
        else:
            return 'default'

    @classmethod
    def validate_file_size(cls, filename: str, size: int) -> bool:
        file_type = cls.get_file_type(filename)
        max_size = cls.MAX_FILE_SIZES.get(file_type, cls.MAX_FILE_SIZES['default'])
        return size <= max_size


class EnvironmentManager:
    """Load environment variables from various sources."""

    @staticmethod
    def load_environment() -> None:
        env_files = ['.env.local', '.env', '.env.example']
        for env_file in env_files:
            if os.path.exists(env_file):
                load_dotenv(env_file)
                logger.info(f"Loaded environment from {env_file}")
                break
        defaults = {
            'UPLOAD_DIR': './uploads',
            'MAX_FILE_SIZE_MB': '2048',
            'RATE_LIMIT_PER_MINUTE': '60',
            'SESSION_EXPIRE_HOURS': '24',
            'SUBSCRIPTION_REMINDER_DAYS': '3',
            'ENVIRONMENT': 'production',
            'DEBUG': 'False',
            'DATABASE_ECHO': 'False',
        }
        settings = SettingsManager.load()
        for key, value in {**defaults, **settings}.items():
            os.environ.setdefault(key, str(value))

    @staticmethod
    def validate_required_vars() -> None:
        required_vars = ['BOT_TOKEN', 'API_ID', 'API_HASH']
        missing = []
        for var in required_vars:
            if not os.getenv(var) or os.getenv(var) in ['', 'YOUR_BOT_TOKEN', '0']:
                missing.append(var)
        if missing:
            raise ValueError(
                f"متغیرهای محیطی ضروری موجود نیستند: {', '.join(missing)}\n"
                f"لطفاً فایل .env را با مقادیر صحیح ایجاد کنید"
            )
        logger.info("تمام متغیرهای محیطی ضروری موجود هستند")


class ConfigFactory:
    """Create configuration instance based on environment."""

    @staticmethod
    def create_config(environment: Optional[str] = None) -> TelegramBotConfig:
        if not environment:
            environment = os.getenv('ENVIRONMENT', 'production')
        if environment == 'development':
            return DevelopmentConfig()
        if environment == 'testing':
            return TestingConfig()
        if environment == 'staging':
            return StagingConfig()
        return ProductionConfig()


class DevelopmentConfig(TelegramBotConfig):
    DEBUG: bool = True
    DATABASE_ECHO: bool = True
    RATE_LIMIT_PER_MINUTE: int = 1000
    SESSION_EXPIRE_HOURS: int = 168


class TestingConfig(TelegramBotConfig):
    DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
    MAX_FILE_SIZE_MB: int = 10
    RATE_LIMIT_PER_MINUTE: int = 1000


class StagingConfig(TelegramBotConfig):
    DEBUG: bool = False
    DATABASE_ECHO: bool = False


class ProductionConfig(TelegramBotConfig):
    DEBUG: bool = False
    DATABASE_ECHO: bool = False
    RATE_LIMIT_PER_MINUTE: int = 60


EnvironmentManager.load_environment()
EnvironmentManager.validate_required_vars()

try:
    config: TelegramBotConfig = ConfigFactory.create_config()
    logger.info(f"Configuration loaded successfully for {config.ENVIRONMENT}")
except Exception as e:
    logger.error(f"Failed to load configuration: {e}")
    raise

# Backwards compatibility with previous globals
BOT_TOKEN = config.BOT_TOKEN
DOWNLOAD_DOMAIN = config.DOWNLOAD_DOMAIN
API_ID = config.API_ID
API_HASH = config.API_HASH
ADMIN_IDS = config.admin_ids_set
REQUIRED_CHANNEL = config.REQUIRED_CHANNEL
UPLOAD_DIR = str(config.UPLOAD_DIR)
SUBSCRIPTION_REMINDER_DAYS = config.SUBSCRIPTION_REMINDER_DAYS

security_config = SecurityConfig()
BLOCKED_EXTENSIONS = security_config.BLOCKED_EXTENSIONS
ILLEGAL_PATTERNS = security_config.ILLEGAL_PATTERNS
