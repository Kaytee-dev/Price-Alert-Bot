# utils.py

import logging
from telegram import Update, BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import SUPER_ADMIN_ID, BOT_ERROR_LOGS_ID
from telegram.error import BadRequest
from util.bot_commands import regular_cmds, admin_cmds, super_admin_cmds

from mongo_client import get_collection
ADMINS = set()

logger = logging.getLogger(__name__)


# utils.py (add at the end)
def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

# --- Helper: Message Sender ---
async def send_message(bot, text: str, chat_id, parse_mode="Markdown", admins=None, super_admin=None, disable_web_page_preview=False):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
    except Exception as e:
        logging.error(f"❌ Failed to send message to {chat_id}: {e}")
        if admins:
            for admin_id in admins:
                try:
                    await bot.send_message(chat_id=admin_id, text=f"❌ Failed to send message to {chat_id}: {e}")
                except Exception as inner:
                    logging.error(f"❌ Also failed to notify admin {admin_id}: {inner}")
        try:
            await bot.send_message(chat_id=BOT_ERROR_LOGS_ID, text=f"❌ [Fallback] Failed to send message to {chat_id}: {e}")
        except Exception as super_err:
            logging.error(f"❌ Also failed to notify BOT_LOGS_ID fallback: {super_err}")


async def load_admins():
    """
    Async: Load the list of admin user_ids from MongoDB and ensure all are integers.
    """
    global ADMINS
    collection = get_collection("admins")
    doc = await collection.find_one({"_id": "admin_list"})
    
    if doc and "user_ids" in doc:
        # Cast all user IDs to int safely
        ADMINS = set(int(uid) for uid in doc["user_ids"])
    else:
        ADMINS = set()

    ADMINS.add(int(SUPER_ADMIN_ID))
    logger.info("✅ ADMINS loaded from admins collection for refreshing commands")

async def refresh_user_commands(user_id: int, bot):

    global ADMINS
    if not ADMINS:
        await load_admins()

    if user_id == SUPER_ADMIN_ID:
        commands = regular_cmds + admin_cmds + super_admin_cmds
    elif user_id in ADMINS:
        commands = regular_cmds + admin_cmds
    else:
        commands = regular_cmds

    await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user_id))


class CustomEffectiveChat:
    def __init__(self, id):
        self.id = id


class CustomMessage:
    def __init__(self, chat_id, query, reply_markup=None):
        self.chat_id = chat_id
        self.query = query
        self.reply_markup = reply_markup


    async def reply_text(self, text, parse_mode=None, reply_markup=None, disable_web_page_preview=False):
        if not self.query or not hasattr(self.query, "message"):
            raise ValueError("Query object with message is required to edit text")

        try:
            await self.query.message.edit_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=self.query.message.reply_markup if reply_markup is None else reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except BadRequest as e:
            if "message to edit" in str(e):
                await self.query.message.reply_text(
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            else:
                raise


class CustomUpdate:
    def __init__(self, effective_chat, message):
        self.effective_chat = effective_chat
        self.message = message


def build_custom_update_from_query(query):
    chat_id = str(query.message.chat_id)
    user_id = int(chat_id)
    chat = CustomEffectiveChat(id=user_id)
    message = CustomMessage(chat_id=user_id, query=query)
    return CustomUpdate(effective_chat=chat, message=message)

# Helper function to handle action confirmation
async def confirm_action(update, context, confirm_callback_data, cancel_callback_data, confirm_message):
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=confirm_callback_data)],
        [InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback_data)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(
            confirm_message,
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            confirm_message,
            reply_markup=reply_markup
        )

async def back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Delete the current message
    await query.message.delete()
    # Call the launch function to show the dashboard
    launch_func = context.bot_data.get("launch_dashboard")
    if launch_func:
        return await launch_func(update, context)
    #await launch(update, context)
