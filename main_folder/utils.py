# utils.py
import json
import logging
from telegram import Update, BotCommand, BotCommandScopeChat
from config import SUPER_ADMIN_ID, ADMINS_FILE


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
        if super_admin and (not admins or super_admin not in admins):
            try:
                await bot.send_message(chat_id=super_admin, text=f"❌ [Fallback] Failed to send message to {chat_id}: {e}")
            except Exception as super_err:
                logging.error(f"❌ Also failed to notify SUPER_ADMIN {super_admin}: {super_err}")

def load_admins():
    try:
        with open(ADMINS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


async def refresh_user_commands(user_id: int, bot):
    ADMINS = load_admins()

    regular_cmds = [
        BotCommand("start", "Start tracking tokens"),
        BotCommand("stop", "Stop tracking tokens"),
        BotCommand("add", "Add a token to track"),
        BotCommand("remove", "Remove token"),
        BotCommand("list", "List tracked tokens"),
        BotCommand("reset", "Clear all tracked tokens"),
        BotCommand("help", "Show help message"),
        BotCommand("status", "Show stats of tracked tokens"),
    ]

    admin_cmds = [
        BotCommand("restart", "Restart the bot"),
        BotCommand("alltokens", "List all tracked tokens"),
    ]

    super_admin_cmds = [
        BotCommand("addadmin", "Add a new admin"),
        BotCommand("removeadmin", "Remove an admin"),
        BotCommand("listadmins", "List all admins"),
    ]

    if user_id == SUPER_ADMIN_ID:
        commands = regular_cmds + admin_cmds + super_admin_cmds
    elif user_id in ADMINS:
        commands = regular_cmds + admin_cmds
    else:
        commands = regular_cmds

    await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user_id))