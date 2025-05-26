import logging
import traceback
import html
import json
import os
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import ContextTypes
from config import DATA_DIR, BOT_ERROR_LOGS_ID

logger = logging.getLogger(__name__)
ERROR_LOGS_DIR = os.path.join(DATA_DIR, "error_logs")
os.makedirs(ERROR_LOGS_DIR, exist_ok=True)

MAX_LOG_FILES = 10  # limit for stored error logs

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list).strip()

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_id = f"error_{timestamp}"

    error_log = {
        "error_id": error_id,
        "timestamp": datetime.now().isoformat(),
        "error_message": str(context.error),
        "traceback": tb_list,
        "update": update_str
    }

    # ✅ Save to JSON with readable formatting
    error_file_path = os.path.join(ERROR_LOGS_DIR, f"{error_id}.json")
    try:
        with open(error_file_path, 'w', encoding='utf-8') as file:
            json.dump(error_log, file, ensure_ascii=False, indent=2)
        logger.info(f"Error log saved to {error_file_path}")
    except Exception as e:
        logger.error(f"Failed to save error log: {e}")

    # ✅ Send preview in Telegram
    preview = (
        f"❌ <b>Error ID:</b> {error_id}\n\n"
        f"<b>Error:</b>\n<pre>{html.escape(str(context.error))}</pre>\n\n"
        f"<b>Traceback (preview):</b>\n<pre>{html.escape(tb_string[:1000])}...</pre>\n\n"
        f"<i>📎 Full details attached as JSON</i>"
    )

    if len(preview) > 4096:
        preview = preview[:4093] + "..."

    # ✅ Send preview + file to admin
    try:
        await context.bot.send_message(
            chat_id=BOT_ERROR_LOGS_ID,
            text=preview,
            parse_mode='HTML'
        )

        with open(error_file_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=BOT_ERROR_LOGS_ID,
                document=InputFile(f, filename=os.path.basename(error_file_path)),
                caption=f"📎 Full Error Log: {error_id}"
            )

            prune_old_error_logs(ERROR_LOGS_DIR, MAX_LOG_FILES)

    except Exception as e:
        logger.error(f"Failed to send error preview or log file: {e}")


def prune_old_error_logs(directory: str, max_files: int):
    """Remove oldest error logs if the file count exceeds the threshold."""
    files = [
        os.path.join(directory, f) for f in os.listdir(directory)
        if f.endswith('.json') and os.path.isfile(os.path.join(directory, f))
    ]
    if len(files) <= max_files:
        return

    # Sort files by modification time (oldest first)
    files.sort(key=lambda x: os.path.getmtime(x))
    excess = len(files) - max_files

    for file in files[:excess]:
        try:
            os.remove(file)
            logger.info(f"🗑️ Deleted old error log: {file}")
        except Exception as e:
            logger.warning(f"⚠️ Could not delete {file}: {e}")
