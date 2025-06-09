import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ثبت کاربر
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = {
        "telegram_id": update.effective_user.id,
        "username": update.effective_user.username,
        "full_name": update.effective_user.full_name
    }
    try:
        response = requests.post(f"{API_BASE_URL}/user/register", json=user_data)
        if response.status_code == 200:
            await update.message.reply_text("✅ شما با موفقیت ثبت شدید!")
        else:
            await update.message.reply_text("⚠️ خطا در ثبت نام.")
    except Exception as e:
        await update.message.reply_text("❌ ارتباط با سرور برقرار نشد.")

# هندل فایل‌ها
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or update.message.video or update.message.audio or update.message.photo
    if not file:
        await update.message.reply_text("❌ فایل نامعتبر است.")
        return

    file_name = file.file_name if hasattr(file, 'file_name') else "unknown_file"
    file_size = file.file_size

    blocked_ext = {".exe", ".bat", ".cmd", ".sh", ".msi", ".dll", ".scr", ".ps1"}
    if any(file_name.lower().endswith(ext) for ext in blocked_ext):
        await update.message.reply_text("❌ فرمت فایل مجاز نیست.")
        return

    payload = {
        "original_file_name": file_name,
        "file_size": file_size,
        "is_from_link": False,
        "telegram_file_id": file.file_id,
    }

    try:
        headers = {"X-User-Id": str(update.effective_user.id)}
        response = requests.post(f"{API_BASE_URL}/file/upload", json=payload, headers=headers)
        if response.status_code == 200:
            file_info = response.json()
            await update.message.reply_text(
                f"✅ لینک دانلود فایل شما: {file_info['direct_download_url']}"
            )
        else:
            await update.message.reply_text("⚠️ خطا در ثبت فایل.")
    except Exception as e:
        await update.message.reply_text("❌ خطا در ارتباط با سرور.")


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send list of user's files."""
    headers = {"X-User-Id": str(update.effective_user.id)}
    try:
        response = requests.get(f"{API_BASE_URL}/file/list", headers=headers)
        if response.status_code == 200:
            files = response.json()
            if not files:
                await update.message.reply_text("📂 لیست فایل‌های شما خالی است.")
            else:
                msg = "\n".join(f"{f['id']} - {f['original_file_name']}" for f in files)
                await update.message.reply_text(msg)
        else:
            await update.message.reply_text("⚠️ خطا در دریافت لیست فایل‌ها.")
    except Exception:
        await update.message.reply_text("❌ ارتباط با سرور برقرار نشد.")


async def delete_file_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a file by its ID."""
    if not context.args:
        await update.message.reply_text("استفاده: /delete <file_id>")
        return
    file_id = context.args[0]
    headers = {"X-User-Id": str(update.effective_user.id)}
    try:
        response = requests.delete(f"{API_BASE_URL}/file/delete/{file_id}", headers=headers)
        if response.status_code == 200:
            await update.message.reply_text("✅ فایل حذف شد.")
        else:
            await update.message.reply_text("⚠️ خطا در حذف فایل.")
    except Exception:
        await update.message.reply_text("❌ ارتباط با سرور برقرار نشد.")


async def upload_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download a file from a URL and save it."""
    if not context.args:
        await update.message.reply_text("استفاده: /uploadlink <URL>")
        return
    url = context.args[0]
    if url.lower().startswith("magnet:") or ".torrent" in url.lower():
        await update.message.reply_text("❌ لینک غیرمجاز است.")
        return
    file_name = url.split("/")[-1]
    blocked_ext = {".exe", ".bat", ".cmd", ".sh", ".msi", ".dll", ".scr", ".ps1"}
    if any(file_name.lower().endswith(ext) for ext in blocked_ext):
        await update.message.reply_text("❌ فرمت فایل مجاز نیست.")
        return
    payload = {
        "url": url,
        "file_name": file_name
    }
    headers = {"X-User-Id": str(update.effective_user.id)}
    try:
        response = requests.post(f"{API_BASE_URL}/file/upload_link", json=payload, headers=headers)
        if response.status_code == 200:
            file_info = response.json()
            await update.message.reply_text(f"✅ لینک دانلود فایل: {file_info['direct_download_url']}")
        else:
            await update.message.reply_text("⚠️ خطا در دانلود فایل.")
    except Exception:
        await update.message.reply_text("❌ ارتباط با سرور برقرار نشد.")

# اجرای ربات
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("files", list_files))
    app.add_handler(CommandHandler("delete", delete_file_cmd))
    app.add_handler(CommandHandler("uploadlink", upload_link))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.Video.ALL | filters.Audio.ALL | filters.PHOTO, handle_file))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
