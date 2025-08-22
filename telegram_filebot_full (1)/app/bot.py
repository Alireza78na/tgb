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
from collections import defaultdict

from app.core.decorators import (
    admin_required,
    user_registered,
    check_channel_membership,
    check_bot_paused,
    set_bot_paused_state,
    get_bot_paused_state,
    is_admin,
)

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN")
if not ADMIN_API_TOKEN:
    raise ValueError("ADMIN_API_TOKEN environment variable not set.")

API_BASE_URL = os.getenv("API_BASE_URL", "http://backend:8000")
MAX_CONCURRENT_TASKS = 5
logger = logging.getLogger(__name__)


# --- API Communication ---
async def api_request(method: str, endpoint: str, *, headers=None, json=None, params=None) -> tuple[int, dict | None]:
    """Perform an HTTP request using aiohttp and return status and JSON."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=json, params=params) as resp:
                data = None
                if resp.content_type == "application/json":
                    try:
                        data = await resp.json()
                    except aiohttp.ContentTypeError:
                        logger.warning(f"Non-JSON response from {endpoint}")
                        data = None
                return resp.status, data
    except aiohttp.ClientConnectorError as e:
        logger.error(f"API connection error: {e}")
        return 0, None
    except Exception as e:
        logger.error(f"Unexpected API request error: {e}", exc_info=True)
        return 0, None


# --- User Management ---
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
    if status == 200 and data and (uid := data.get("id")):
        context.user_data["user_id"] = uid
        return uid
    return None


import asyncio

# --- Task Management (Temporary) ---
# This active_downloads dictionary is now only used for non-link file uploads,
# which are still synchronous. The link uploads use the new task queue system.
@dataclass
class DownloadTask:
    chat_id: int
    message_id: int
    cancel: bool = False

active_downloads: dict[int, list[DownloadTask]] = defaultdict(list)


# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


# --- Command Handlers ---
@check_bot_paused
@check_channel_membership
@user_registered
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ شما با موفقیت ثبت شدید!")


@check_channel_membership
@user_registered
async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID شما: {context.user_data['user_id']}")


@check_bot_paused
@check_channel_membership
@user_registered
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or update.message.video or update.message.audio or update.message.photo
    if not file:
        await update.message.reply_text("❌ فایل نامعتبر است.")
        return

    file_name = getattr(file, 'file_name', "unknown_file")
    if any(file_name.lower().endswith(ext) for ext in {".exe", ".bat", ".sh"}):
        await update.message.reply_text("❌ فرمت فایل مجاز نیست.")
        return

    if len(active_downloads[update.effective_user.id]) >= MAX_CONCURRENT_TASKS:
        await update.message.reply_text("❌ حداکثر تعداد پردازش همزمان مجاز شد")
        return

    payload = {
        "original_file_name": file_name,
        "file_size": file.file_size,
        "is_from_link": False,
        "telegram_file_id": file.file_id,
    }
    headers = {"X-User-Id": context.user_data["user_id"]}

    # This part will be refactored in a later step
    task = DownloadTask(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    active_downloads[update.effective_user.id].append(task)
    try:
        status, data = await api_request("POST", "/file/upload", headers=headers, json=payload)
        if status == 200 and data:
            await update.message.reply_text(f"✅ لینک دانلود فایل شما: {data['direct_download_url']}")
        else:
            await update.message.reply_text(f"⚠️ خطا در ثبت فایل. (Code: {status})")
    except Exception as e:
        logger.error(f"Error handling file upload: {e}", exc_info=True)
        await update.message.reply_text("❌ خطا در ارتباط با سرور.")
    finally:
        active_downloads[update.effective_user.id].remove(task)


@check_bot_paused
@check_channel_membership
@user_registered
async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    headers = {"X-User-Id": context.user_data["user_id"]}
    status, data = await api_request("GET", "/file/list", headers=headers)

    if status == 200 and data and data.get("files"):
        files = data["files"]
        for f in files:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 لینک جدید", callback_data=f"regen:{f['id']}")],
                [InlineKeyboardButton("❌ حذف", callback_data=f"del:{f['id']}")]
            ])
            await update.message.reply_text(f"{f['original_file_name']}", reply_markup=keyboard)
    elif status == 200:
        await update.message.reply_text("📂 لیست فایل‌های شما خالی است.")
    else:
        await update.message.reply_text("⚠️ خطا در دریافت لیست فایل‌ها.")


@check_bot_paused
@check_channel_membership
@user_registered
async def delete_file_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /delete <id1> <id2> ... یا /delete all")
        return

    headers = {"X-User-Id": context.user_data["user_id"]}
    if context.args[0].lower() == "all":
        status, data = await api_request("GET", "/file/list", headers=headers)
        if status == 200 and data and data.get("files"):
            ids = [f['id'] for f in data["files"]]
            await api_request("POST", "/file/delete_bulk", headers=headers, json=ids)
            await update.message.reply_text("✅ همه فایل‌ها حذف شد")
        else:
            await update.message.reply_text("⚠️ خطایی رخ داد یا فایلی برای حذف وجود ندارد.")
        return

    status, _ = await api_request("POST", "/file/delete_bulk", headers=headers, json=context.args)
    if status == 200:
        await update.message.reply_text("✅ عملیات حذف انجام شد")
    else:
        await update.message.reply_text("⚠️ خطا در حذف فایل‌ها")


@check_bot_paused
@check_channel_membership
@user_registered
async def upload_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /uploadlink <URL>")
        return

    url = context.args[0]
    # Basic URL validation
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("❌ لینک نامعتبر است. باید با http یا https شروع شود.")
        return

    file_name = url.split("/")[-1].split("?")[0] or "download"

    payload = {"url": url, "file_name": file_name}
    headers = {"X-User-Id": context.user_data["user_id"]}

    # 1. Start the download task on the backend
    status, data = await api_request("POST", "/file/upload_link", headers=headers, json=payload)

    if status == 400: # For cases like invalid URL or filename caught by backend
        await update.message.reply_text(f"⚠️ خطا: {data.get('detail', 'درخواست نامعتبر')}")
        return
    if status != 202 or not data or "task_id" not in data:
        await update.message.reply_text(f"⚠️ خطا در شروع دانلود در سرور. (Code: {status})")
        return

    task_id = data["task_id"]

    # 2. Send a message to the user that the task has started
    status_msg = await update.message.reply_text(
        "☑️ درخواست دانلود شما ثبت شد. در حال بررسی...",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("لغو", callback_data=f"cancel:{task_id}")]
        ])
    )

    # 3. Poll for the task status
    last_status = None
    for _ in range(180): # Poll for up to 30 minutes (180 * 10s)
        await asyncio.sleep(10)
        status, task_data = await api_request("GET", f"/task/{task_id}/status", headers=headers)

        if status != 200 or not task_data:
            # If task status is not found, it might be completed and cleaned up, or an error occurred.
            # We stop polling. The final message should have been set by the completed task.
            logger.warning(f"Could not retrieve status for task {task_id}, stopping poll.")
            break

        current_status = task_data.get("status")
        if current_status == last_status:
            continue # Don't edit the message if status hasn't changed

        last_status = current_status
        message_text = f"وضعیت دانلود: {current_status}"

        if current_status == "completed":
            result = task_data.get("result", {})
            if result.get("success"):
                message_text = f"✅ دانلود با موفقیت انجام شد!\nلینک شما: {result['direct_download_url']}"
                await context.bot.edit_message_text(
                    chat_id=status_msg.chat.id, message_id=status_msg.message_id,
                    text=message_text, reply_markup=None
                )
            else:
                message_text = f"❌ دانلود با خطا مواجه شد.\nدلیل: {result.get('error', 'نامشخص')}"
                await context.bot.edit_message_text(
                    chat_id=status_msg.chat.id, message_id=status_msg.message_id,
                    text=message_text, reply_markup=None
                )
            break # Exit loop on completion
        elif current_status in ["failed", "cancelled", "timeout"]:
            error_reason = task_data.get("error", "نامشخص")
            message_text = f"❌ دانلود ناموفق بود.\nوضعیت: {current_status}\nدلیل: {error_reason}"
            await context.bot.edit_message_text(
                chat_id=status_msg.chat.id, message_id=status_msg.message_id,
                text=message_text, reply_markup=None
            )
            break # Exit loop on failure

        # Update progress message for running/pending states
        try:
            await context.bot.edit_message_text(
                chat_id=status_msg.chat.id, message_id=status_msg.message_id,
                text=message_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("لغو", callback_data=f"cancel:{task_id}")]
                ])
            )
        except Exception as e:
            logger.warning(f"Failed to edit message for task {task_id}: {e}")
            break # Stop polling if we can't edit the message
    else:
        # Loop finished without breaking (timeout)
        await context.bot.edit_message_text(
            chat_id=status_msg.chat.id, message_id=status_msg.message_id,
            text="⌛️ پاسخ از سرور برای دانلود دریافت نشد. لطفاً بعداً وضعیت را با دستور /files بررسی کنید.",
            reply_markup=None
        )


@check_bot_paused
@check_channel_membership
@user_registered
async def my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    headers = {"X-User-Id": context.user_data["user_id"]}
    status, info = await api_request("GET", "/user/subscription", headers=headers)
    if status == 200 and info:
        await update.message.reply_text(f"پلن فعلی: {info['plan_name']}\nانقضا: {info['end_date']}")
    else:
        await update.message.reply_text("اشتراکی برای شما فعال نیست.")


# --- Admin Handlers ---
@admin_required
async def pause_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_bot_paused_state(True)
    await update.message.reply_text("✅ Bot paused")


@admin_required
async def resume_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_bot_paused_state(False)
    await update.message.reply_text("✅ Bot resumed")


@admin_required
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /broadcast <message>")
        return
    message = " ".join(context.args)
    await update.message.reply_text("در حال ارسال...")
    await api_request(
        "POST", "/admin/broadcast",
        params={"message": message},
        headers={"X-Admin-Token": ADMIN_API_TOKEN},
    )


@admin_required
async def cancel_all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for tasks in active_downloads.values():
        for t in tasks:
            t.cancel = True
    await update.message.reply_text("تمام پردازش‌ها لغو شد")


@admin_required
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_btn = "▶️ ادامه ربات" if get_bot_paused_state() else "⏸ توقف ربات"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 پلن‌ها", callback_data="admin:plans")],
        [InlineKeyboardButton("👥 کاربران", callback_data="admin:users")],
        [InlineKeyboardButton(status_btn, callback_data="admin:toggle")],
        [InlineKeyboardButton("📣 ارسال همگانی", callback_data="admin:broadcast")],
        [InlineKeyboardButton("❌ لغو دانلودها", callback_data="admin:cancel_all")],
    ])
    target = update.message or update.callback_query.message
    await target.reply_text("پنل ادمین:", reply_markup=keyboard)


# --- Callback Query Handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, _, data = query.data.partition(":")

    handler_map = {
        "del": handle_delete_query,
        "regen": handle_regenerate_query,
        "admin": handle_admin_query,
        "delplan": handle_delete_plan_query,
        "blockuser": handle_block_user_query,
        "unblockuser": handle_unblock_user_query,
        "cancel": handle_cancel_query,
    }

    if handler := handler_map.get(action):
        await handler(update, context, data)
    else:
        logger.warning(f"Unhandled button action: {action}")

async def handle_delete_query(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
    await user_registered(lambda u,c: None)(update, context) # Ensure user_id exists
    if not context.user_data.get("user_id"): return

    headers = {"X-User-Id": context.user_data["user_id"]}
    status, _ = await api_request("DELETE", f"/file/delete/{file_id}", headers=headers)
    await update.callback_query.edit_message_text("✅ فایل حذف شد" if status == 200 else "⚠️ خطا در حذف فایل")

async def handle_regenerate_query(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
    await user_registered(lambda u,c: None)(update, context)
    if not context.user_data.get("user_id"): return

    headers = {"X-User-Id": context.user_data["user_id"]}
    status, info = await api_request("POST", f"/file/regenerate/{file_id}", headers=headers)
    if status == 200 and info:
        await update.callback_query.edit_message_text(f"🔗 لینک جدید: {info['direct_download_url']}")
    else:
        await update.callback_query.edit_message_text("⚠️ خطا در ایجاد لینک جدید")

async def handle_cancel_query(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: str):
    """Handles the 'cancel' button press for a download task."""
    if not task_id:
        await update.callback_query.answer("Invalid task ID.", show_alert=True)
        return

    await user_registered(lambda u, c: None)(update, context)
    if not context.user_data.get("user_id"):
        await update.callback_query.answer("Could not identify user.", show_alert=True)
        return

    headers = {"X-User-Id": context.user_data["user_id"]}
    status, data = await api_request("POST", f"/task/{task_id}/cancel", headers=headers)

    if status == 200:
        await update.callback_query.answer("درخواست لغو ارسال شد.")
        await update.callback_query.edit_message_text("درخواست لغو برای این دانلود ارسال شد.")
    elif status == 400:
        await update.callback_query.answer(data.get("detail", "Task cannot be cancelled."), show_alert=True)
    else:
        await update.callback_query.answer("خطا در ارسال درخواست لغو.", show_alert=True)

@admin_required
async def handle_admin_query(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str):
    if command == "toggle":
        set_bot_paused_state(not get_bot_paused_state())
        await admin_menu(update, context)
    elif command == "cancel_all":
        await cancel_all_cmd(update, context)
    elif command == "broadcast":
        await update.callback_query.message.reply_text("برای ارسال پیام از دستور /broadcast استفاده کنید")
    # Other admin commands can be added here
    else:
        await update.callback_query.message.reply_text(f"Admin action '{command}' not implemented yet.")

@admin_required
async def handle_delete_plan_query(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_id: str):
    headers = {"X-Admin-Token": ADMIN_API_TOKEN}
    status, _ = await api_request("DELETE", f"/admin/plan/{plan_id}", headers=headers)
    await update.callback_query.edit_message_text("پلن حذف شد" if status == 200 else "خطا در حذف پلن")

@admin_required
async def handle_block_user_query(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str):
    headers = {"X-Admin-Token": ADMIN_API_TOKEN}
    status, _ = await api_request("POST", f"/admin/user/block/{user_id}", headers=headers)
    await update.callback_query.edit_message_text("کاربر مسدود شد" if status == 200 else "خطا در عملیات")

@admin_required
async def handle_unblock_user_query(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str):
    headers = {"X-Admin-Token": ADMIN_API_TOKEN}
    status, _ = await api_request("POST", f"/admin/user/unblock/{user_id}", headers=headers)
    await update.callback_query.edit_message_text("کاربر آزاد شد" if status == 200 else "خطا در عملیات")


# --- Main Application Setup ---
def main():
    """Sets up and runs the bot."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command Handlers
    handlers = [
        CommandHandler("start", start),
        CommandHandler("myid", my_id),
        CommandHandler("files", list_files),
        CommandHandler("delete", delete_file_cmd),
        CommandHandler("uploadlink", upload_link),
        CommandHandler("mysub", my_subscription),
        CommandHandler("pausebot", pause_bot),
        CommandHandler("resumebot", resume_bot),
        CommandHandler("broadcast", broadcast_cmd),
        CommandHandler("cancelall", cancel_all_cmd),
        CommandHandler("admin", admin_menu),
        MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO, handle_file),
        CallbackQueryHandler(button_handler),
    ]
    app.add_handlers(handlers)

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
