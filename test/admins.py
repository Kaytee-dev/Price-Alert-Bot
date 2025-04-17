import logging
from typing import Callable
from telegram import Update
from telegram.ext import ContextTypes
from utils import load_json, save_json

ADMINS_FILE = "admins.json"
ADMINS = set()

# --- Super Admin ID ---
SUPER_ADMIN_ID = -4710110042  
# --- Load/Save Admins ---
def load_admins():
    global ADMINS
    ADMINS = set(load_json(ADMINS_FILE, [], "admins"))

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
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    if user_id in ADMINS:
        await update.message.reply_text(f"ℹ️ User {user_id} is already an admin.")
    else:
        ADMINS.add(user_id)
        save_admins()
        await update.message.reply_text(f"✅ Added user {user_id} as admin.")
