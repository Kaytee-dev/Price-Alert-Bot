# utils.py
import json
import logging
from telegram import Update, BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import SUPER_ADMIN_ID, ADMINS_FILE, BOT_ERROR_LOGS_ID
from telegram.error import BadRequest


def load_json(file_path: str, fallback, log_label: str = ""):
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            logging.info(f"📂 Loaded {log_label or file_path}.")
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        logging.info(f"📂 No valid {log_label or file_path} found. Starting fresh.")
        return fallback.copy() if isinstance(fallback, dict) else list(fallback)

def save_json(file_path: str, data, log_label: str = ""):
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        logging.info(f"💾 Saved {log_label or file_path}.")
    except Exception as e:
        logging.error(f"❌ Failed to save {log_label or file_path}: {e}")

# utils.py (add at the end)
def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

# --- Helper: Message Sender ---
# async def send_message(bot, text: str, chat_id, parse_mode="Markdown", admins=None, super_admin=None):
#     try:
#         await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
#     except Exception as e:
#         logging.error(f"❌ Failed to send message to {chat_id}: {e}")
#         if admins:
#             for admin_id in admins:
#                 try:
#                     await bot.send_message(chat_id=admin_id, text=f"❌ Failed to send message to {chat_id}: {e}")
#                 except Exception as inner:
#                     logging.error(f"❌ Also failed to notify admin {admin_id}: {inner}")
#         if super_admin and (not admins or super_admin not in admins):
#             try:
#                 await bot.send_message(chat_id=super_admin, text=f"❌ [Fallback] Failed to send message to {chat_id}: {e}")
#             except Exception as super_err:
#                 logging.error(f"❌ Also failed to notify SUPER_ADMIN {super_admin}: {super_err}")

async def send_message(bot, text: str, chat_id, parse_mode="Markdown", admins=None, super_admin=None):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
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


def load_admins():
    try:
        with open(ADMINS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


async def refresh_user_commands(user_id: int, bot):

    ADMINS = load_admins()

    regular_cmds = [
        BotCommand("lc", "Launch bot dashboard"),
        BotCommand("start", "Start tracking tokens"),
        BotCommand("stop", "Stop tracking tokens"),
        BotCommand("add", "Add a token to track -- /a"),
        BotCommand("remove", "Remove token from tracking -- /rm"),
        BotCommand("list", "List tracked tokens -- /l"),
        BotCommand("reset", "Clear all tracked tokens -- /x"),
        BotCommand("help", "Show help message -- /h"),
        BotCommand("status", "Show stats of tracked tokens -- /s"),
        BotCommand("threshold", "Set your spike alert threshold (%) -- /t"),
    ]

    admin_cmds = [
        BotCommand("restart", "Restart the bot -- /rs"),
        BotCommand("alltokens", "List all tracked tokens -- /at"),
        BotCommand("checkpayment", "Retrieve user payment log -- /cp"),
        BotCommand("manualupgrade", "Manually upgrade user tier -- /mu"),
        BotCommand("processpayouts", "Process referral commission -- /pp"),
        BotCommand("listrefs", "View user referral data -- /lr"),

    ]

    super_admin_cmds = [
        BotCommand("addadmin", "Add a new admin -- /aa"),
        BotCommand("removeadmin", "Remove an admin -- /ra"),
        BotCommand("listadmins", "List all admins -- /la"),
        BotCommand("addwallet", "Add new wallet -- /aw"),
        BotCommand("addpayout", "Add payout wallet -- /ap"),
        BotCommand("listwallet", "Add payout wallet -- /lw"),
        BotCommand("removewallet", "Remove regular wallets -- /rm"),
        BotCommand("removepayout", "Remove payout wallets -- /rp"),
        
    ]

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


