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
import aiohttp
import asyncio


async def api_request(method: str, endpoint: str, *, headers=None, json=None, params=None) -> tuple[int, dict | None]:
    """Perform an HTTP request using aiohttp and return status and JSON."""
    url = f"{API_BASE_URL}{endpoint}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.request(method, url, headers=headers, json=json, params=params) as resp:
                data = None
                if resp.content_type == "application/json":
                    try:
                        data = await resp.json()
                    except Exception:
                        data = None
                return resp.status, data
        except Exception:
            return 0, None


async def get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Ensure the user is registered and return their backend ID."""
    if uid := context.user_data.get("user_id"):
        return uid

    payload = {
        "telegram_id": update.effective_user.id,
        "username": update.effective_user.username,
        "full_name": update.effective_user.full_name,
    }

    status, data = await api_request("POST", "/user/register", json=payload)
    if status == 200 and data:
        uid = data.get("id")
        if uid:
            context.user_data["user_id"] = uid
            return uid
    return None

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
# When using Docker Compose the backend service is reachable via the
# 'backend' hostname inside the bot container. Default to that URL so
# the bot can talk to the API without additional configuration.
API_BASE_URL = os.getenv("API_BASE_URL", "http://backend:8000")
ADMIN_IDS = {int(uid) for uid in os.getenv("ADMIN_IDS", "").split(",") if uid}
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL")
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


async def ensure_channel_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is member of REQUIRED_CHANNEL."""
    if not REQUIRED_CHANNEL or is_admin(update.effective_user.id):
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, update.effective_user.id)
        if member.status in ("member", "creator", "administrator"):
            return True
    except Exception:
        pass
    await update.effective_message.reply_text("برای استفاده از ربات ابتدا در کانال عضو شوید")
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
    if not await ensure_channel_member(update, context):
        return
    uid = await get_user_id(update, context)
    if uid:
        await update.message.reply_text("✅ شما با موفقیت ثبت شدید!")
    else:
        await update.message.reply_text("⚠️ خطا در ثبت نام.")


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_channel_member(update, context):
        return
    uid = await get_user_id(update, context)
    if uid:
        await update.message.reply_text(f"ID شما: {uid}")
    else:
        await update.message.reply_text("⚠️ خطا در دریافت شناسه شما")

# هندل فایل‌ها
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
    if not await ensure_channel_member(update, context):
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
        uid = await get_user_id(update, context)
        if not uid:
            await update.message.reply_text("⚠️ خطا در ثبت نام.")
            return
        headers = {"X-User-Id": uid}
        task = DownloadTask(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        active_downloads[update.effective_user.id].append(task)
        status, data = await api_request("POST", "/file/upload", headers=headers, json=payload)
        if status == 200 and data:
            file_info = data
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
    if not await ensure_channel_member(update, context):
        return
    uid = await get_user_id(update, context)
    if not uid:
        await update.message.reply_text("⚠️ خطا در ثبت نام.")
        return
    headers = {"X-User-Id": uid}
    try:
        status, data = await api_request("GET", "/file/list", headers=headers)
        if status == 200 and data is not None:
            files = data
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
    if not await ensure_channel_member(update, context):
        return
    if not context.args:
        await update.message.reply_text("استفاده: /delete <id1> <id2> ... یا /delete all")
        return
    uid = await get_user_id(update, context)
    if not uid:
        await update.message.reply_text("⚠️ خطا در ثبت نام.")
        return
    headers = {"X-User-Id": uid}
    if context.args[0].lower() == "all":
        status, data = await api_request("GET", "/file/list", headers=headers)
        if status == 200 and data is not None:
            ids = [f['id'] for f in data]
            await api_request("POST", "/file/delete_bulk", headers=headers, json=ids)
            await update.message.reply_text("✅ همه فایل‌ها حذف شد")
        else:
            await update.message.reply_text("⚠️ خطا در دریافت لیست")
        return

    ids = context.args
    status, _ = await api_request("POST", "/file/delete_bulk", headers=headers, json=ids)
    if status == 200:
        await update.message.reply_text("✅ عملیات حذف انجام شد")
    else:
        await update.message.reply_text("⚠️ خطا در حذف فایل‌ها")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not await ensure_channel_member(update, context):
        return
    if data.startswith("cancel:"):
        uid = int(data.split(":", 1)[1])
        tasks = active_downloads.get(uid, [])
        for t in tasks:
            t.cancel = True
    elif data.startswith("del:"):
        file_id = data.split(":", 1)[1]
        uid = await get_user_id(update, context)
        if not uid:
            await query.edit_message_text("⚠️ خطا در ثبت نام")
            return
        headers = {"X-User-Id": uid}
        status, _ = await api_request("DELETE", f"/file/delete/{file_id}", headers=headers)
        if status == 200:
            await query.edit_message_text("✅ فایل حذف شد")
        else:
            await query.edit_message_text("⚠️ خطا در حذف فایل")
    elif data.startswith("regen:"):
        file_id = data.split(":", 1)[1]
        uid = await get_user_id(update, context)
        if not uid:
            await query.edit_message_text("⚠️ خطا در ثبت نام")
            return
        headers = {"X-User-Id": uid}
        status, info = await api_request("POST", f"/file/regenerate/{file_id}", headers=headers)
        if status == 200 and info:
            await query.edit_message_text(f"🔗 لینک جدید: {info['direct_download_url']}")
        else:
            await query.edit_message_text("⚠️ خطا در ایجاد لینک جدید")
    elif data.startswith("admin:") and is_admin(update.effective_user.id):
        action = data.split(":", 1)[1]
        admin_headers = {"X-Admin-Token": os.getenv("ADMIN_API_TOKEN", "SuperSecretAdminToken123")}
        if action == "plans":
            status, data = await api_request("GET", "/admin/plan", headers=admin_headers)
            if status == 200 and data is not None:
                plans = data
                if not plans:
                    await query.message.reply_text("پلنی وجود ندارد")
                for p in plans:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ حذف", callback_data=f"delplan:{p['id']}")]])
                    await query.message.reply_text(f"{p['name']} - {p['id']}", reply_markup=kb)
            else:
                await query.message.reply_text("خطا در دریافت پلن‌ها")
        elif action == "users":
            status, data = await api_request("GET", "/admin/users", headers=admin_headers)
            if status == 200 and data is not None:
                users = data
                if not users:
                    await query.message.reply_text("کاربری یافت نشد")
                for u in users[:10]:
                    if u.get("is_blocked"):
                        cd = f"unblockuser:{u['id']}"
                        btn_text = "🔓 رفع مسدودی"
                    else:
                        cd = f"blockuser:{u['id']}"
                        btn_text = "🔒 مسدود"
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data=cd)]])
                    name = u.get("full_name") or ""
                    uname = f"@{u['username']}" if u.get('username') else ""
                    await query.message.reply_text(f"{name} {uname} - {u['telegram_id']}", reply_markup=kb)
            else:
                await query.message.reply_text("خطا در دریافت کاربران")
        elif action == "toggle":
            global BOT_PAUSED
            BOT_PAUSED = not BOT_PAUSED
            await admin_menu(update, context)
        elif action == "broadcast":
            await query.message.reply_text("برای ارسال پیام از دستور /broadcast استفاده کنید")
        elif action == "cancel_all":
            for tasks in active_downloads.values():
                for t in tasks:
                    t.cancel = True
            await query.message.reply_text("تمام دانلودها لغو شد")
        return
    elif data.startswith("delplan:") and is_admin(update.effective_user.id):
        plan_id = data.split(":", 1)[1]
        admin_headers = {"X-Admin-Token": os.getenv("ADMIN_API_TOKEN", "SuperSecretAdminToken123")}
        status, _ = await api_request("DELETE", f"/admin/plan/{plan_id}", headers=admin_headers)
        if status == 200:
            await query.edit_message_text("پلن حذف شد")
        else:
            await query.edit_message_text("خطا در حذف پلن")
    elif data.startswith("blockuser:") and is_admin(update.effective_user.id):
        uid = data.split(":", 1)[1]
        admin_headers = {"X-Admin-Token": os.getenv("ADMIN_API_TOKEN", "SuperSecretAdminToken123")}
        status, _ = await api_request("POST", f"/admin/user/block/{uid}", headers=admin_headers)
        if status == 200:
            await query.edit_message_text("کاربر مسدود شد")
        else:
            await query.edit_message_text("خطا در عملیات")
    elif data.startswith("unblockuser:") and is_admin(update.effective_user.id):
        uid = data.split(":", 1)[1]
        admin_headers = {"X-Admin-Token": os.getenv("ADMIN_API_TOKEN", "SuperSecretAdminToken123")}
        status, _ = await api_request("POST", f"/admin/user/unblock/{uid}", headers=admin_headers)
        if status == 200:
            await query.edit_message_text("کاربر آزاد شد")
        else:
            await query.edit_message_text("خطا در عملیات")


async def upload_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download a file from a URL and save it."""
    if bot_paused(update):
        await update.message.reply_text("⛔️ Bot under maintenance.")
        return
    if not await ensure_channel_member(update, context):
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
    uid = await get_user_id(update, context)
    if not uid:
        await update.message.reply_text("⚠️ خطا در ثبت نام.")
        return
    headers = {"X-User-Id": uid}
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
        status, data = await api_request("POST", "/file/upload_link", headers=headers, json=payload)
        if status == 200 and not task.cancel and data:
            file_info = data
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
    if not await ensure_channel_member(update, context):
        return
    uid = await get_user_id(update, context)
    if not uid:
        await update.message.reply_text("⚠️ خطا در ثبت نام.")
        return
    headers = {"X-User-Id": uid}
    try:
        status, info = await api_request("GET", "/user/subscription", headers=headers)
        if status == 200 and info is not None:
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
    await api_request(
        "POST",
        "/admin/broadcast",
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


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display admin control panel."""
    if not is_admin(update.effective_user.id):
        return
    status_btn = "\u23F8 توقف ربات" if not BOT_PAUSED else "\u25B6\ufe0f ادامه ربات"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("\U0001F4CA \u067e\u0644\u0646\u200c\u0647\u0627", callback_data="admin:plans")],
            [InlineKeyboardButton("\U0001F465 \u06a9\u0627\u0631\u0628\u0631\u0627\u0646", callback_data="admin:users")],
            [InlineKeyboardButton(status_btn, callback_data="admin:toggle")],
            [InlineKeyboardButton("\U0001F4E3 \u0627\u0631\u0633\u0627\u0644 \u0647\u0645\u06af\u0627\u0646\u06cc", callback_data="admin:broadcast")],
            [InlineKeyboardButton("\u274C \u0644\u063a\u0648 \u0647\u0645\u0647 \u062f\u0627\u0646\u0644\u0648\u062f\u0647\u0627", callback_data="admin:cancel_all")],
        ]
    )
    if update.message:
        await update.message.reply_text("پنل ادمین:", reply_markup=keyboard)
    else:
        await update.callback_query.message.edit_text("پنل ادمین:", reply_markup=keyboard)

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
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.AUDIO | filters.PHOTO,
            handle_file,
        )
    )
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
