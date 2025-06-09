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
ADMIN_IDS = {int(uid) for uid in os.getenv("ADMIN_IDS", "").split(",") if uid}
BOT_PAUSED = False


@dataclass
class DownloadTask:
    chat_id: int
    message_id: int
    cancel: bool = False


from collections import defaultdict

MAX_CONCURRENT_TASKS = 5
active_downloads: dict[int, list[DownloadTask]] = defaultdict(list)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def bot_paused(update: Update) -> bool:
    if BOT_PAUSED and not is_admin(update.effective_user.id):
        return True
    return False

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ثبت کاربر
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
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
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
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

    if len(active_downloads[update.effective_user.id]) >= MAX_CONCURRENT_TASKS:
        await update.message.reply_text("❌ حداکثر تعداد پردازش همزمان مجاز شد")
        return

    payload = {
        "original_file_name": file_name,
        "file_size": file_size,
        "is_from_link": False,
        "telegram_file_id": file.file_id,
    }

    try:
        headers = {"X-User-Id": str(update.effective_user.id)}
        task = DownloadTask(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        active_downloads[update.effective_user.id].append(task)
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
    finally:
        active_downloads[update.effective_user.id].remove(task)


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send list of user's files."""
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
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
    """Delete one or multiple files."""
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
    if not context.args:
        await update.message.reply_text("استفاده: /delete <id1> <id2> ... یا /delete all")
        return
    headers = {"X-User-Id": str(update.effective_user.id)}
    if context.args[0].lower() == "all":
        list_resp = requests.get(f"{API_BASE_URL}/file/list", headers=headers)
        if list_resp.status_code == 200:
            ids = [f['id'] for f in list_resp.json()]
            requests.post(f"{API_BASE_URL}/file/delete_bulk", json=ids, headers=headers)
            await update.message.reply_text("✅ همه فایل‌ها حذف شد")
        else:
            await update.message.reply_text("⚠️ خطا در دریافت لیست")
        return

    ids = context.args
    resp = requests.post(f"{API_BASE_URL}/file/delete_bulk", json=ids, headers=headers)
    if resp.status_code == 200:
        await update.message.reply_text("✅ عملیات حذف انجام شد")
    else:
        await update.message.reply_text("⚠️ خطا در حذف فایل‌ها")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("cancel:"):
        uid = int(data.split(":", 1)[1])
        tasks = active_downloads.get(uid, [])
        for t in tasks:
            t.cancel = True
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
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
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
    if len(active_downloads[update.effective_user.id]) >= MAX_CONCURRENT_TASKS:
        await update.message.reply_text("❌ حداکثر تعداد پردازش همزمان مجاز شد")
        return
    status_msg = await update.message.reply_text(
        "⏬ در حال دانلود...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("لغو", callback_data=f"cancel:{update.effective_user.id}")]]
        ),
    )
    task = DownloadTask(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
    active_downloads[update.effective_user.id].append(task)
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
        if task in active_downloads[update.effective_user.id]:
            active_downloads[update.effective_user.id].remove(task)


async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
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


async def pause_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    global BOT_PAUSED
    BOT_PAUSED = True
    await update.message.reply_text("✅ Bot paused")


async def resume_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    global BOT_PAUSED
    BOT_PAUSED = False
    await update.message.reply_text("✅ Bot resumed")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) or not context.args:
        return
    message = " ".join(context.args)
    await update.message.reply_text("در حال ارسال...")
    requests.post(
        f"{API_BASE_URL}/admin/broadcast",
        params={"message": message},
        headers={"X-Admin-Token": os.getenv("ADMIN_API_TOKEN", "SuperSecretAdminToken123")},
    )


async def cancel_all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    for tasks in active_downloads.values():
        for t in tasks:
            t.cancel = True
    await update.message.reply_text("تمام پردازش‌ها لغو شد")

# اجرای ربات
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("files", list_files))
    app.add_handler(CommandHandler("delete", delete_file_cmd))
    app.add_handler(CommandHandler("deleteall", lambda u, c: delete_file_cmd(u, c)))
    app.add_handler(CommandHandler("uploadlink", upload_link))
    app.add_handler(CommandHandler("mysub", my_subscription))
    app.add_handler(CommandHandler("pausebot", pause_bot))
    app.add_handler(CommandHandler("resumebot", resume_bot))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("cancelall", cancel_all_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.Video.ALL | filters.Audio.ALL | filters.PHOTO, handle_file))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
