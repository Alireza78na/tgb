import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

# Pre-load admin IDs and required channel from environment variables
ADMIN_IDS = {int(uid) for uid in os.getenv("ADMIN_IDS", "").split(",") if uid}
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL")

# A simple flag for the bot's paused state, managed by admin commands
BOT_PAUSED = False

def is_admin(user_id: int) -> bool:
    """Checks if a user is an admin."""
    return user_id in ADMIN_IDS

def admin_required(func):
    """Decorator to restrict a handler to admins only."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not is_admin(update.effective_user.id):
            await update.effective_message.reply_text("⛔️ This command is for admins only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def user_registered(func):
    """Decorator to ensure the user is registered with the backend."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if "user_id" not in context.user_data:
            from app.bot import get_user_id  # Local import to avoid circular dependency
            user_id = await get_user_id(update, context)
            if not user_id:
                await update.effective_message.reply_text("⚠️ Could not register or identify you. Please try again.")
                return
        return await func(update, context, *args, **kwargs)
    return wrapper

def check_channel_membership(func):
    """Decorator to check if the user is a member of the required channel."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not REQUIRED_CHANNEL or is_admin(update.effective_user.id):
            return await func(update, context, *args, **kwargs)

        try:
            member = await context.bot.get_chat_member(REQUIRED_CHANNEL, update.effective_user.id)
            if member.status in ("member", "creator", "administrator"):
                return await func(update, context, *args, **kwargs)
        except Exception:
            pass  # Fall through to the error message

        await update.effective_message.reply_text("برای استفاده از ربات ابتدا در کانال عضو شوید")
    return wrapper

def check_bot_paused(func):
    """Decorator to check if the bot is paused."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if BOT_PAUSED and not is_admin(update.effective_user.id):
            await update.effective_message.reply_text("⛔️ Bot is currently under maintenance. Please try again later.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def get_bot_paused_state() -> bool:
    """Returns the current paused state of the bot."""
    return BOT_PAUSED

def set_bot_paused_state(paused: bool):
    """Sets the paused state of the bot."""
    global BOT_PAUSED
    BOT_PAUSED = paused
