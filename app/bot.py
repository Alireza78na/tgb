import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import requests

BOT_TOKEN = "YOUR_BOT_TOKEN"
API_BASE_URL = "http://localhost:8000"

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

    payload = {
        "original_file_name": file_name,
        "file_size": file_size,
        "is_from_link": False
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

# اجرای ربات
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.Video.ALL | filters.Audio.ALL | filters.PHOTO, handle_file))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
