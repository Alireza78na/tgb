import os
import secrets
from typing import List, Optional, Any
from pydantic import BaseSettings, validator, Field
from functools import lru_cache
import json
from pathlib import Path

class TelegramBotSettings(BaseSettings):
    """تنظیمات ربات تلگرام با اعتبارسنجی کامل"""

    # Bot Configuration
    BOT_TOKEN: str = Field(..., min_length=45, description="توکن ربات تلگرام")
    API_ID: int = Field(..., gt=0, description="شناسه API تلگرام")
    API_HASH: str = Field(..., min_length=32, max_length=32, description="Hash API تلگرام")

    # Domain and URLs
    DOWNLOAD_DOMAIN: str = Field(..., description="دامنه اصلی سرور")
    BACKEND_URL: str = Field(default="http://localhost:8000", description="آدرس backend")
    WEBHOOK_URL: Optional[str] = Field(None, description="آدرس webhook")

    # File Management
    UPLOAD_DIR: str = Field(default="/var/www/filebot/uploads", description="پوشه آپلود فایل‌ها")
    MAX_FILE_SIZE: int = Field(default=2*1024*1024*1024, description="حداکثر اندازه فایل (بایت)")
    ALLOWED_EXTENSIONS: List[str] = Field(
        default=[".jpg", ".png", ".pdf", ".mp4", ".zip", ".rar"],
        description="فرمت‌های مجاز"
    )
    BLOCKED_EXTENSIONS: List[str] = Field(
        default=[".exe", ".bat", ".sh", ".cmd", ".scr"],
        description="فرمت‌های مسدود شده"
    )

    # Admin Configuration
    ADMIN_IDS: List[int] = Field(default_factory=list, description="شناسه‌های ادمین")
    SUPER_ADMIN_ID: Optional[int] = Field(None, description="ادمین اصلی")

    # Channel Configuration
    REQUIRED_CHANNEL: Optional[str] = Field(None, description="کانال اجباری")
    LOG_CHANNEL: Optional[str] = Field(None, description="کانال لاگ")

    # Subscription Settings
    SUBSCRIPTION_REMINDER_DAYS: int = Field(default=7, ge=1, le=30, description="روزهای یادآوری")
    DEFAULT_TRIAL_DAYS: int = Field(default=7, ge=0, le=30, description="روزهای آزمایشی")

    # Security Settings
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    ENCRYPTION_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    # Rate Limiting
    RATE_LIMIT_MESSAGES: int = Field(default=20, description="حد پیام در دقیقه")
    RATE_LIMIT_FILES: int = Field(default=5, description="حد فایل در ساعت")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://user:pass@localhost/filebot",
        description="آدرس دیتابیس"
    )
    REDIS_URL: str = Field(default="redis://localhost:6379", description="آدرس Redis")

    # Monitoring
    ENABLE_METRICS: bool = Field(default=True, description="فعال‌سازی metrics")
    LOG_LEVEL: str = Field(default="INFO", description="سطح لاگ")
    SENTRY_DSN: Optional[str] = Field(None, description="Sentry DSN برای error tracking")

    # Performance
    MAX_CONCURRENT_DOWNLOADS: int = Field(default=10, description="حداکثر دانلود همزمان")
    CLEANUP_INTERVAL_HOURS: int = Field(default=24, description="فاصله پاکسازی")

    # Environment
    ENVIRONMENT: str = Field(default="development", description="محیط اجرا")
    DEBUG: bool = Field(default=False, description="حالت debug")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> Any:
            if field_name in ["ADMIN_IDS", "ALLOWED_EXTENSIONS", "BLOCKED_EXTENSIONS"]:
                try:
                    return json.loads(raw_val)
                except Exception:
                    return raw_val.split(",") if raw_val else []
            return raw_val

    @validator("BOT_TOKEN")
    def validate_bot_token(cls, v: str) -> str:
        if v == "YOUR_BOT_TOKEN" or len(v) < 45:
            raise ValueError("BOT_TOKEN معتبر وارد کنید (از @BotFather)")
        import re
        if not re.match(r'^\d{8,10}:[a-zA-Z0-9_-]{35}$', v):
            raise ValueError("فرمت BOT_TOKEN نامعتبر است")
        return v

    @validator("API_HASH")
    def validate_api_hash(cls, v: str) -> str:
        if not v or len(v) != 32:
            raise ValueError("API_HASH باید 32 کاراکتر باشد (از my.telegram.org)")
        import re
        if not re.match(r'^[a-fA-F0-9]{32}$', v):
            raise ValueError("API_HASH فقط باید شامل کاراکترهای hex باشد")
        return v.lower()

    @validator("DOWNLOAD_DOMAIN")
    def validate_domain(cls, v: str) -> str:
        if v == "yourdomain.com" or not v:
            raise ValueError("DOWNLOAD_DOMAIN معتبر وارد کنید")
        import re
        pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError("فرمت DOWNLOAD_DOMAIN نامعتبر است")
        return v.lower()

    @validator("UPLOAD_DIR")
    def validate_upload_dir(cls, v: str) -> str:
        upload_path = Path(v)
        try:
            upload_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise ValueError(f"عدم دسترسی برای ایجاد پوشه: {v}")
        if not os.access(upload_path, os.W_OK):
            raise ValueError(f"عدم دسترسی نوشتن در پوشه: {v}")
        return str(upload_path.resolve())

    @validator("ADMIN_IDS")
    def validate_admin_ids(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("حداقل یک ADMIN_ID الزامی است")
        for admin_id in v:
            if admin_id <= 0 or admin_id > 9999999999:
                raise ValueError(f"شناسه ادمین نامعتبر: {admin_id}")
        return list(set(v))

    @validator("REQUIRED_CHANNEL")
    def validate_channel(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        channel = v.strip().lstrip('@')
        import re
        if channel.startswith('-100'):
            if not re.match(r'^-100\d{10,}$', v):
                raise ValueError("فرمت Chat ID نامعتبر است")
        else:
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', channel):
                raise ValueError("فرمت username کانال نامعتبر است")
            v = f"@{channel}"
        return v

    def get_webhook_url(self) -> Optional[str]:
        if self.WEBHOOK_URL:
            return self.WEBHOOK_URL
        elif self.DOWNLOAD_DOMAIN:
            return f"https://{self.DOWNLOAD_DOMAIN}/bot/webhook"
        return None

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.ADMIN_IDS or user_id == self.SUPER_ADMIN_ID

    def get_file_url(self, file_path: str) -> str:
        return f"https://{self.DOWNLOAD_DOMAIN}/files/{file_path}"

@lru_cache()
def get_settings() -> TelegramBotSettings:
    return TelegramBotSettings()


def create_env_example():
    env_example = """
# Telegram Bot Configuration
BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890

# Domain Configuration
DOWNLOAD_DOMAIN=files.example.com
BACKEND_URL=http://localhost:8000
WEBHOOK_URL=https://files.example.com/bot/webhook

# File Management
UPLOAD_DIR=/var/www/filebot/uploads
MAX_FILE_SIZE=2147483648
ALLOWED_EXTENSIONS=["jpg","png","pdf","mp4","zip"]
BLOCKED_EXTENSIONS=["exe","bat","sh","cmd"]

# Admin Configuration
ADMIN_IDS=[123456789,987654321]
SUPER_ADMIN_ID=123456789

# Channel Configuration
REQUIRED_CHANNEL=@yourchannel
LOG_CHANNEL=@logchannel

# Subscription Settings
SUBSCRIPTION_REMINDER_DAYS=7
DEFAULT_TRIAL_DAYS=7

# Security (Generate new values!)
SECRET_KEY=your-secret-key-here
ENCRYPTION_KEY=your-encryption-key
JWT_SECRET=your-jwt-secret

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/filebot
REDIS_URL=redis://localhost:6379

# Performance
RATE_LIMIT_MESSAGES=20
RATE_LIMIT_FILES=5
MAX_CONCURRENT_DOWNLOADS=10

# Environment
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
ENABLE_METRICS=true
"""
    with open(".env.example", "w", encoding="utf-8") as f:
        f.write(env_example.strip())


def setup_configuration():
    import shutil
    print("🚀 راه‌اندازی تنظیمات ربات تلگرام...")
    create_env_example()
    print("✅ فایل .env.example ایجاد شد")
    if not Path(".env").exists():
        print("📝 فایل .env یافت نشد. آیا می‌خواهید از .env.example کپی کنید؟")
        if input("(y/N): ").lower() == 'y':
            shutil.copy(".env.example", ".env")
            print("✅ فایل .env از .env.example کپی شد")
            print("⚠️  لطفاً فایل .env را با مقادیر واقعی تکمیل کنید")
    upload_dir = Path("./uploads")
    upload_dir.mkdir(exist_ok=True)
    print(f"✅ پوشه آپلود در {upload_dir.resolve()} ایجاد شد")
    print("🔒 برای راه‌اندازی SSL با Let's Encrypt:")
    print("   sudo certbot --nginx -d yourdomain.com")
    print("\n🎉 راه‌اندازی کامل شد!")
    print("📋 مراحل بعدی:")
    print("   1. فایل .env را با مقادیر واقعی تکمیل کنید")
    print("   2. دیتابیس PostgreSQL را راه‌اندازی کنید")
    print("   3. Redis را نصب و راه‌اندازی کنید")
    print("   4. Nginx را تنظیم کنید")
    print("   5. SSL certificate دریافت کنید")


def validate_production_config():
    try:
        settings = get_settings()
        issues = []
        if settings.DEBUG and settings.ENVIRONMENT == "production":
            issues.append("DEBUG نباید در production فعال باشد")
        if settings.SECRET_KEY == "your-secret-key-here":
            issues.append("SECRET_KEY باید تغییر کند")
        if not settings.SENTRY_DSN and settings.ENVIRONMENT == "production":
            issues.append("SENTRY_DSN برای production توصیه می‌شود")
        if not Path(settings.UPLOAD_DIR).exists():
            issues.append(f"پوشه آپلود وجود ندارد: {settings.UPLOAD_DIR}")
        if "localhost" in settings.DATABASE_URL and settings.ENVIRONMENT == "production":
            issues.append("DATABASE_URL برای production نامناسب است")
        if issues:
            print("❌ مشکلات تنظیمات:")
            for issue in issues:
                print(f"   • {issue}")
            return False
        else:
            print("✅ تنظیمات معتبر است")
            return True
    except Exception as e:
        print(f"❌ خطا در اعتبارسنجی: {e}")
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "setup":
            setup_configuration()
        elif sys.argv[1] == "validate":
            validate_production_config()
        elif sys.argv[1] == "example":
            create_env_example()
    else:
        print("استفاده:")
        print("  python config.py setup    - راه‌اندازی اولیه")
        print("  python config.py validate - اعتبارسنجی تنظیمات")
        print("  python config.py example  - ایجاد .env.example")

settings = get_settings()
config = settings
