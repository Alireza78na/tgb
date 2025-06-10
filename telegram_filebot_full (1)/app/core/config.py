from .settings_manager import SettingsManager

settings = SettingsManager.load()

BOT_TOKEN = settings.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
DOWNLOAD_DOMAIN = settings.get("DOWNLOAD_DOMAIN", "yourdomain.com")
API_ID = int(settings.get("API_ID", 0))
API_HASH = settings.get("API_HASH", "")

ADMIN_IDS = {int(uid) for uid in str(settings.get("ADMIN_IDS", "")).split(",") if uid}
REQUIRED_CHANNEL = settings.get("REQUIRED_CHANNEL")

UPLOAD_DIR = settings.get("UPLOAD_DIR", "./uploads")

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".msi", ".dll", ".scr", ".ps1"
}

ILLEGAL_PATTERNS = ["magnet:", ".torrent"]

SUBSCRIPTION_REMINDER_DAYS = int(settings.get("SUBSCRIPTION_REMINDER_DAYS", 3))
