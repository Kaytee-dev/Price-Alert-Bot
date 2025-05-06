import logging
import traceback
import html
import json
import os
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from config import DATA_DIR, BOT_ERROR_LOGS_ID


logger = logging.getLogger(__name__)


# Directory for error logs
ERROR_LOGS_DIR = f"{DATA_DIR}error_logs"

# Ensure error logs directory exists
os.makedirs(ERROR_LOGS_DIR, exist_ok=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors, save full logs to JSON, and notify admin."""
    # Log the error
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Get traceback info
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)
    
    # Get update info
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    
    # Create a timestamp for the error
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_id = f"error_{timestamp}"
    
    # Create error log dictionary
    error_log = {
        "error_id": error_id,
        "timestamp": datetime.now().isoformat(),
        "error_message": str(context.error),
        "traceback": tb_string,
        "update": update_str
    }
    
    # Save full error log to JSON file
    error_file_path = os.path.join(ERROR_LOGS_DIR, f"{error_id}.json")
    try:
        with open(error_file_path, 'w', encoding='utf-8') as file:
            json.dump(error_log, file, ensure_ascii=False, indent=2)
        logger.info(f"Error log saved to {error_file_path}")
    except Exception as e:
        logger.error(f"Failed to save error log: {e}")
    
    # Build the message with truncated error details for Telegram
    message = (
        f"❌ <b>Error ID:</b> {error_id}\n\n"
        f"<b>Error:</b> \n<pre>{html.escape(str(context.error))}</pre>\n\n"
        f"<b>Traceback:</b> \n<pre>{html.escape(tb_string[:2000] + '...' if len(tb_string) > 2000 else tb_string)}</pre>\n\n"
        f"<i>Full error details saved to {error_id}.json</i>"
    )
    
    # If message is still too long, truncate further
    if len(message) > 4096:
        message = message[:4093] + "..."
    
    # Send error message to admin
    try:
        await context.bot.send_message(
            chat_id=BOT_ERROR_LOGS_ID,
            text=message,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Failed to send error notification: {e}")
