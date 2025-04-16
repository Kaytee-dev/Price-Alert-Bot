# token_alert_bot.py

import asyncio
import json
import logging
from typing import Dict, List
import time
import hashlib
from datetime import datetime
import os
import sys

from typing import Optional
import requests
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Globals ---
TRACKED_TOKENS: List[str] = []  # List of Solana token addresses
TRACKED_TOKENS_FILE = "tracked_tokens_multi.json"
ADDRESS_TO_SYMBOL: Dict[str, str] = {}
SYMBOLS_FILE = "symbols_multi.json"
POLL_INTERVAL = 60  # seconds
BOT_TOKEN = "7645462301:AAGPzpLZ03ddKIzQb3ovADTWYMztD9cKGNY"

USER_CHAT_ID: int | None = None
ADMIN_CHAT_ID = -4750674293
BASE_URL = "https://gmgn.ai/sol/token/"

# Cache for recent token data
TOKEN_DATA_HISTORY: Dict[str, List[dict]] = {}
TOKEN_HISTORY_FILE = "token_history_multi.json"
LAST_SAVED_HASHES: Dict[str, str] = {}

MONITOR_TASK: Optional[asyncio.Task] = None

# Multi user feature
USER_TRACKING_FILE = "user_tracking.json"
USER_TRACKING = {}

logging.basicConfig(level=logging.INFO)

# --- Admin-only decorator ---
def restricted_to_admin(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != ADMIN_CHAT_ID:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper


# --- Generic JSON Utilities ---
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

# --- Load/Save User Tracking ---
def load_user_tracking():
    global USER_TRACKING
    USER_TRACKING = load_json(USER_TRACKING_FILE, {}, "user tracking")

def save_user_tracking():
    save_json(USER_TRACKING_FILE, USER_TRACKING, "user tracking")

# --- Symbol Persistence ---
def load_symbols_from_file():
    global ADDRESS_TO_SYMBOL
    ADDRESS_TO_SYMBOL = load_json(SYMBOLS_FILE, {}, "symbols")

def save_symbols_to_file():
    save_json(SYMBOLS_FILE, ADDRESS_TO_SYMBOL, "symbols")

# --- Token History Persistence ---
def load_token_history():
    global TOKEN_DATA_HISTORY
    TOKEN_DATA_HISTORY = load_json(TOKEN_HISTORY_FILE, {}, "token history")

    for addr, history in TOKEN_DATA_HISTORY.items():
        if history:
            latest = history[0]
            hash_val = hashlib.md5(json.dumps(latest, sort_keys=True).encode()).hexdigest()
            LAST_SAVED_HASHES[addr] = hash_val

def save_token_history():
    for addr in list(TOKEN_DATA_HISTORY.keys()):
        if addr not in TRACKED_TOKENS:
            del TOKEN_DATA_HISTORY[addr]
            LAST_SAVED_HASHES.pop(addr, None)

    save_json(TOKEN_HISTORY_FILE, TOKEN_DATA_HISTORY, "token history")

# --- Tracked Tokens Persistence ---
def load_tracked_tokens():
    global TRACKED_TOKENS
    TRACKED_TOKENS = load_json(TRACKED_TOKENS_FILE, [], "tracked tokens")

def save_tracked_tokens():
    save_json(TRACKED_TOKENS_FILE, TRACKED_TOKENS, "tracked tokens")


# --- Dexscreener Fetcher ---
def fetch_prices_for_tokens(addresses: List[str], max_retries: int = 3, retry_delay: int = 2) -> List[dict]:
    token_query = ",".join(addresses)
    url = f"https://api.dexscreener.com/tokens/v1/solana/{token_query}"

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                logging.warning(f"📡 Attempt {attempt}: Non-200 response ({response.status_code})")

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
            logging.warning(f"🌐 Attempt {attempt}: Network error: {net_err}")
        except requests.exceptions.RequestException as req_err:
            logging.warning(f"⚠️ Attempt {attempt}: General request failure: {req_err}")
        except Exception as e:
            logging.warning(f"❌ Attempt {attempt}: Unexpected error: {e}")

        if attempt < max_retries:
            backoff = retry_delay * (2 ** (attempt - 1))
            time.sleep(backoff)

    logging.error("🚫 All retry attempts failed.")
    return []


# --- Helper: Chunking ---
def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

# --- Helper: Message Sender ---
async def send_message(bot, text: str, chat_id, parse_mode="Markdown"):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"❌ Failed to send message to {chat_id}: {e}")
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Failed to send message to {chat_id}: {e}")
            except Exception as inner:
                logging.error(f"❌ Also failed to notify admin: {inner}")

# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_TASK

    await context.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("stop", "Stop the bot"),
        BotCommand("add", "Add a token to track"),
        BotCommand("alltokens", "List tracked tokens by all user(admin only)"),
        BotCommand("remove", "Remove token"),
        BotCommand("list", "List tracked tokens"),
        BotCommand("reset", "Clear all tracked tokens"),
        BotCommand("help", "Show help message"),
        BotCommand("restart", "Restart the bot (admin only)"),
        BotCommand("status", "Show stats of tracked tokens")
    ])

    await update.message.reply_text("🤖 Bot started and monitoring tokens!")
    if MONITOR_TASK is None or MONITOR_TASK.done():
        MONITOR_TASK = context.application.create_task(background_price_monitor(context.application))

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MONITOR_TASK
    if MONITOR_TASK and not MONITOR_TASK.done():
        MONITOR_TASK.cancel()
        await update.message.reply_text("🛑 Monitoring task stopped.")
    else:
        await update.message.reply_text("ℹ️ No active monitoring task to stop.")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return

    if chat_id not in USER_TRACKING:
        USER_TRACKING[chat_id] = []

    added = []
    skipped = []

    for address in addresses:
        if address not in USER_TRACKING[chat_id]:
            USER_TRACKING[chat_id].append(address)
            added.append(address)
            if address not in TRACKED_TOKENS:
                TRACKED_TOKENS.append(address)
        else:
            skipped.append(address)

    save_user_tracking()
    save_tracked_tokens()

    if added:
        await update.message.reply_text(f"✅ Tracking token(s):\n" + "\n".join(added))
    if skipped:
        await update.message.reply_text(f"ℹ️ Already tracked:\n" + "\n".join(skipped))



async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ...")
        return

    if chat_id not in USER_TRACKING:
        await update.message.reply_text("ℹ️ You're not tracking any tokens.")
        return

    removed = []
    not_found = []
    tokens_removed = []

    for address in addresses:
        if address in USER_TRACKING[chat_id]:
            USER_TRACKING[chat_id].remove(address)
            removed.append(address)
        else:
            not_found.append(address)

    # Clean up global tracked list
    for token in removed:
        if not any(token in tokens for tokens in USER_TRACKING.values()):
            if token in TRACKED_TOKENS:
                TRACKED_TOKENS.remove(token)
                tokens_removed.append(token)
                ADDRESS_TO_SYMBOL.pop(token, None)
                TOKEN_DATA_HISTORY.pop(token, None)
                LAST_SAVED_HASHES.pop(token, None)

    save_user_tracking()
    save_tracked_tokens()
    save_symbols_to_file()
    save_token_history()

    if removed:
        await update.message.reply_text(f"🗑️ Removed token(s):\n" + "\n".join(removed))
    if not_found:
        await update.message.reply_text(f"❌ Address(es) not found in your tracking list:\n" + "\n".join(not_found))
    if tokens_removed:
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) from tracking after /remove."
        logging.info(msg)
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)

async def list_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    user_tokens = USER_TRACKING.get(chat_id, [])
    if not user_tokens:
        await update.message.reply_text("📭 You're not tracking any tokens.")
        return

    msg = "📊 Your Tracked Tokens:\n"

    for addr in user_tokens:
        symbol = ADDRESS_TO_SYMBOL.get(addr, addr[:6] + "...")
        link = f"[{symbol}]({BASE_URL}{addr})"

        history = TOKEN_DATA_HISTORY.get(addr, [])
        market_cap = history[0].get("marketCap") if history else None
        mc_text = f" - Market Cap: ${market_cap:,.0f}" if market_cap else ""

        msg += f"- {link} ({addr[:6]}...{addr[-4:]}){mc_text}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    tokens_removed = []

    user_tokens = USER_TRACKING.get(chat_id, [])
    if chat_id in USER_TRACKING:
        USER_TRACKING.pop(chat_id, None)
        logging.info(f"🧹 Removed user {chat_id} from tracking.")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🧹 Removed user {chat_id} from tracking.")

    # Clean tracked tokens that are no longer used
    for token in user_tokens:
        if not any(token in tokens for tokens in USER_TRACKING.values()):
            if token in TRACKED_TOKENS:
                TRACKED_TOKENS.remove(token)
                tokens_removed.append(token)
                ADDRESS_TO_SYMBOL.pop(token, None)
                TOKEN_DATA_HISTORY.pop(token, None)
                LAST_SAVED_HASHES.pop(token, None)

    save_user_tracking()
    save_tracked_tokens()
    save_symbols_to_file()
    save_token_history()

    if tokens_removed:
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) from tracking after /reset."
        logging.info(msg)
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)

    await update.message.reply_text("🔄 Your tracked tokens, symbols, and history have been cleared.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *Price Alert Bot Help*\n\n"
        "Use the following commands to manage your token alerts:\n"
        "\n/start - Start the bot and monitoring"
        "\n/stop - Stop the bot monitoring"
        "\n/add <token1>, <token2>, ... - Track token(s)"
        "\n/remove <token1>, <token2>, ... - Stop tracking token(s)"
        "\n/list - Show your tracked tokens"
        "\n/reset - Clear all your tracking data"
        "\n/help - Show this help message"
        "\n/status - Show stats of tracked token(s)"
        "\n/alltokens - Show all unique token(s) tracked by all user (admin only)"
        "\n\nEach user can track their own set of tokens independently."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_tokens = USER_TRACKING.get(chat_id, [])
    all_tokens = set(addr for tokens in USER_TRACKING.values() for addr in tokens)

    spike_count = 0
    for addr in all_tokens:
        history = TOKEN_DATA_HISTORY.get(addr, [])
        if history and isinstance(history[0].get("priceChange_m5"), (int, float)):
            if history[0]["priceChange_m5"] >= 15:
                spike_count += 1

    last_update = None
    timestamps = [entry[0].get("timestamp") for entry in TOKEN_DATA_HISTORY.values() if entry]
    if timestamps:
        last_update = max(timestamps)

    msg = (
        f"📊 *Bot Status*\n\n"
        f"👤 You are tracking {len(user_tokens)} token(s).\n"
        f"🌐 Total unique tokens tracked: {len(all_tokens)}\n"
        f"💥 Active spikes (≥15%): {spike_count}\n"
        f"🕓 Last update: {last_update if last_update else 'N/A'}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

@restricted_to_admin
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("♻️ Restarting bot...")
    await context.application.shutdown()
    os.execl(sys.executable, sys.executable, *sys.argv)

@restricted_to_admin
async def alltokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_tokens = set(addr for tokens in USER_TRACKING.values() for addr in tokens)
    if not all_tokens:
        await update.message.reply_text("📭 No tokens are being tracked by any user.")
        return

    def get_market_cap(addr):
        history = TOKEN_DATA_HISTORY.get(addr, [])
        return history[0].get("marketCap") if history else None

    sorted_tokens = sorted(all_tokens, key=lambda addr: (get_market_cap(addr) is None, -(get_market_cap(addr) or 0)))

    msg = f"📦 *All Tracked Tokens (Total: {len(all_tokens)}):*\n\n"
    for addr in sorted_tokens:
        symbol = ADDRESS_TO_SYMBOL.get(addr, addr[:6] + "...")
        link = f"[{symbol}]({BASE_URL}{addr})"
        market_cap = get_market_cap(addr)
        mc_text = f" - Market Cap: ${market_cap:,.0f}" if market_cap else ""
        msg += f"- {link} ({addr[:6]}...{addr[-4:]}){mc_text}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# --- Price Monitor Background Task ---
def background_price_monitor(app):
    async def monitor():
        while True:
            save_needed = False
            if TRACKED_TOKENS:
                for chunk in chunked(TRACKED_TOKENS, 30):
                    token_data_list = fetch_prices_for_tokens(chunk)
                    for data in token_data_list:
                        base = data.get("baseToken", {})
                        address = base.get("address")
                        if not address:
                            continue

                        if address not in ADDRESS_TO_SYMBOL:
                            symbol = base.get("symbol", address[:6])
                            ADDRESS_TO_SYMBOL[address] = symbol
                            save_symbols_to_file()

                        symbol = ADDRESS_TO_SYMBOL.get(address)
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Format: YYYY-MM-DD HH:MM:SS

                        # Keep only relevant fields with timestamp
                        cleaned_data = {
                            "timestamp": timestamp,
                            "address": address,
                            "symbol": symbol,
                            "priceChange_m5": data.get("priceChange", {}).get("m5"),
                            "volume_m5": data.get("volume", {}).get("m5"),
                            "marketCap": data.get("marketCap")
                        }

                        if address not in TOKEN_DATA_HISTORY:
                            TOKEN_DATA_HISTORY[address] = []
                        TOKEN_DATA_HISTORY[address].insert(0, cleaned_data)
                        TOKEN_DATA_HISTORY[address] = TOKEN_DATA_HISTORY[address][:3]

                        # Compute hash and compare
                        snapshot_json = json.dumps(cleaned_data, sort_keys=True)
                        hash_val = hashlib.md5(snapshot_json.encode()).hexdigest()

                        if LAST_SAVED_HASHES.get(address) != hash_val:
                            LAST_SAVED_HASHES[address] = hash_val
                            save_needed = True

                        # Threshold-based alert logic
                        history = TOKEN_DATA_HISTORY[address][:3]
                        recent_changes = [
                            entry.get("priceChange_m5")
                            for entry in history
                            if isinstance(entry.get("priceChange_m5"), (int, float))
                        ]


                        change = cleaned_data.get("priceChange_m5")
                        if isinstance(change, (int, float)) and change >= 15 and any(p >= 15 for p in recent_changes[1:]):
                            link = f"[{cleaned_data['symbol']}]({BASE_URL}{address})"
                            msg = (
                                f"📢 {link} is spiking!\n"
                                f"5m Change: {cleaned_data['priceChange_m5']}%\n"
                                f"5m Volume: ${cleaned_data['volume_m5']:,.2f}\n"
                                f"Market Cap: ${cleaned_data['marketCap']:,.0f}"
                            )

                            for chat_id, tokens in USER_TRACKING.items():
                                if address in tokens:
                                    await send_message(app.bot, msg, chat_id=chat_id, parse_mode="Markdown")
                            

            if save_needed:
                await asyncio.to_thread(save_token_history)

            await asyncio.sleep(POLL_INTERVAL)

    return monitor()


# --- Bot Runner ---
def main():
    load_symbols_from_file()
    load_token_history()  # ✅ Restore TOKEN_DATA_HISTORY and LAST_SAVED_HASHES
    load_tracked_tokens()
    load_user_tracking()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("alltokens", alltokens))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_tokens))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("status", status))

    app.run_polling()

if __name__ == "__main__":
    main()
