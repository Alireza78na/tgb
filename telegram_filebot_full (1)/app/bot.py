import logging
from dataclasses import dataclass
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@dataclass
class DownloadTask:
    chat_id: int
    message_id: int
    cancel: bool = False


active_downloads: dict[int, DownloadTask] = {}

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


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID شما: {update.effective_user.id}")

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
                for f in files:
                    keyboard = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("🔗 لینک جدید", callback_data=f"regen:{f['id']}"),
                                InlineKeyboardButton("❌ حذف", callback_data=f"del:{f['id']}")
                            ]
                        ]
                    )
                    await update.message.reply_text(
                        f"{f['original_file_name']}", reply_markup=keyboard
                    )
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


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("cancel:"):
        uid = int(data.split(":", 1)[1])
        task = active_downloads.get(uid)
        if task:
            task.cancel = True
    elif data.startswith("del:"):
        file_id = data.split(":", 1)[1]
        headers = {"X-User-Id": str(update.effective_user.id)}
        resp = requests.delete(f"{API_BASE_URL}/file/delete/{file_id}", headers=headers)
        if resp.status_code == 200:
            await query.edit_message_text("✅ فایل حذف شد")
        else:
            await query.edit_message_text("⚠️ خطا در حذف فایل")
    elif data.startswith("regen:"):
        file_id = data.split(":", 1)[1]
        headers = {"X-User-Id": str(update.effective_user.id)}
        resp = requests.post(f"{API_BASE_URL}/file/regenerate/{file_id}", headers=headers)
        if resp.status_code == 200:
            info = resp.json()
            await query.edit_message_text(f"🔗 لینک جدید: {info['direct_download_url']}")
        else:
            await query.edit_message_text("⚠️ خطا در ایجاد لینک جدید")


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
    payload = {"url": url, "file_name": file_name}
    headers = {"X-User-Id": str(update.effective_user.id)}
    status_msg = await update.message.reply_text(
        "⏬ در حال دانلود...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("لغو", callback_data=f"cancel:{update.effective_user.id}")]]
        ),
    )
    task = DownloadTask(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
    active_downloads[update.effective_user.id] = task
    try:
        response = requests.post(f"{API_BASE_URL}/file/upload_link", json=payload, headers=headers)
        if response.status_code == 200 and not task.cancel:
            file_info = response.json()
            await context.bot.edit_message_text(
                chat_id=task.chat_id,
                message_id=task.message_id,
                text=f"✅ لینک دانلود فایل: {file_info['direct_download_url']}"
            )
        elif task.cancel:
            await context.bot.edit_message_text(
                chat_id=task.chat_id,
                message_id=task.message_id,
                text="❌ دانلود لغو شد"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=task.chat_id,
                message_id=task.message_id,
                text="⚠️ خطا در دانلود فایل."
            )
    except Exception:
        await context.bot.edit_message_text(
            chat_id=task.chat_id,
            message_id=task.message_id,
            text="❌ ارتباط با سرور برقرار نشد."
        )
    finally:
        active_downloads.pop(update.effective_user.id, None)


async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    headers = {"X-User-Id": str(update.effective_user.id)}
    try:
        resp = requests.get(f"{API_BASE_URL}/user/subscription", headers=headers)
        if resp.status_code == 200:
            info = resp.json()
            text = f"پلن فعلی: {info['plan_name']}\nانقضا: {info['end_date']}"
            await update.message.reply_text(text)
        else:
            await update.message.reply_text("اشتراکی برای شما فعال نیست.")
    except Exception:
        await update.message.reply_text("❌ ارتباط با سرور برقرار نشد.")

# اجرای ربات
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("files", list_files))
    app.add_handler(CommandHandler("delete", delete_file_cmd))
    app.add_handler(CommandHandler("uploadlink", upload_link))
    app.add_handler(CommandHandler("mysub", my_subscription))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.Video.ALL | filters.Audio.ALL | filters.PHOTO, handle_file))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
