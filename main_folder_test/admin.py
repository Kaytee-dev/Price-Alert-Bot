import logging
from typing import Callable
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils import load_json, save_json
from config import ADMINS_FILE, SUPER_ADMIN_ID

import storage.tiers as tiers

ADMINS = set()

# --- Super Admin ID ---
#SUPER_ADMIN_ID = -4710110042  # Replace this with your actual ID

# --- Load/Save Admins ---
def load_admins():
    global ADMINS
    ADMINS = set(load_json(ADMINS_FILE, [], "admins"))
    ADMINS.add(SUPER_ADMIN_ID)  # ensure super admin is always present

def save_admins():
    save_json(ADMINS_FILE, list(ADMINS), "admins")

# --- Admin Decorators ---
def restricted_to_admin(func: Callable):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in ADMINS:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper

def restricted_to_super_admin(func: Callable):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != SUPER_ADMIN_ID:
            await update.message.reply_text("❌ Only the super admin can perform this action.")
            return
        return await func(update, context)
    return wrapper

# --- Admin Commands ---
@restricted_to_super_admin
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id or @username>")
        return

    arg = context.args[0]
    try:
        if arg.startswith("@"):  # username
            user = await context.bot.get_chat(arg)
        else:
            user_id = int(arg)
            user = await context.bot.get_chat(user_id)

        if not user or user.type != 'private':
            raise ValueError("Not a valid user.")

        user_id = user.id
    except Exception:
        await update.message.reply_text("❌ Invalid Telegram user ID or username.")
        return

    if user_id in ADMINS:
        tiers.promote_to_premium(user_id)
        await update.message.reply_text(f"ℹ️ User {user_id} is already an admin.")
    else:
        ADMINS.add(user_id)
        save_admins()

        tiers.promote_to_premium(user_id)

        await update.message.reply_text(f"✅ Added user {user_id} as admin.")

@restricted_to_super_admin
async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    if user_id not in ADMINS:
        await update.message.reply_text(f"ℹ️ User {user_id} is not an admin.")
    else:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_removeadmin:{user_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_removeadmin")
            ]
        ])
        await update.message.reply_text(
            f"⚠️ Are you sure you want to remove admin `{user_id}`?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@restricted_to_admin
async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMINS:
        await update.message.reply_text("📭 No admins currently set.")
        return

    msg = "👮‍♂️ *Current Admins:*\n"
    for admin_id in sorted(ADMINS):
        badge = "🌟 Super Admin" if admin_id == SUPER_ADMIN_ID else "👤 Admin"
        msg += f"- `{admin_id}` {badge}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# --- Callback for Remove Confirmation ---
@restricted_to_super_admin
async def handle_removeadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_removeadmin:"):
        user_id = int(query.data.split(":")[1])
        if user_id in ADMINS:
            ADMINS.remove(user_id)
            save_admins()
            await query.edit_message_text(f"🗑️ Removed user {user_id} from admins.")
        else:
            await query.edit_message_text(f"ℹ️ User {user_id} is no longer an admin.")

    elif query.data == "cancel_removeadmin":
        await query.edit_message_text("❌ Admin removal cancelled.")
