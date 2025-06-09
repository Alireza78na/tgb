import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
DOWNLOAD_DOMAIN = os.getenv("DOWNLOAD_DOMAIN", "yourdomain.com")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".msi", ".dll", ".scr", ".ps1"
}

ILLEGAL_PATTERNS = ["magnet:", ".torrent"]
