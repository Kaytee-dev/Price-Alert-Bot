# token_alert_bot.py

import asyncio
import json
import logging
from typing import Dict, List
import time
import hashlib
from datetime import datetime

from typing import Optional
import requests
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Globals ---
TRACKED_TOKENS: List[str] = []  # List of Solana token addresses
TRACKED_TOKENS_FILE = "tracked_tokens.json"
ADDRESS_TO_SYMBOL: Dict[str, str] = {}
SYMBOLS_FILE = "symbols.json"
POLL_INTERVAL = 330  # seconds
BOT_TOKEN = "7645462301:AAGPzpLZ03ddKIzQb3ovADTWYMztD9cKGNY"
USER_CHAT_ID: int | None = None
BASE_URL = "https://gmgn.ai/sol/token/"

# Cache for recent token data
TOKEN_DATA_HISTORY: Dict[str, List[dict]] = {}
TOKEN_HISTORY_FILE = "token_history.json"
LAST_SAVED_HASHES: Dict[str, str] = {}

MONITOR_TASK: Optional[asyncio.Task] = None

logging.basicConfig(level=logging.INFO)

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
async def send_message(bot, text: str):
    if USER_CHAT_ID is None:
        logging.warning("⚠️ No user chat ID set. Cannot send message.")
        return
    try:
        await bot.send_message(chat_id=USER_CHAT_ID, text=text)
    except Exception as e:
        logging.error(f"❌ Failed to send message: {e}")

# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    global MONITOR_TASK
    USER_CHAT_ID = update.effective_chat.id

    await context.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("stop", "Stop the bot"),
        BotCommand("add", "Add a token to track"),
        BotCommand("remove", "Remove token"),
        BotCommand("list", "List tracked tokens"),
        BotCommand("reset", "Clear all tracked tokens")
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
    if not context.args:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return

    added = []
    skipped = []

    for address in addresses:
        if address not in TRACKED_TOKENS:
            TRACKED_TOKENS.append(address)
            added.append(address)
        else:
            skipped.append(address)

    save_tracked_tokens()

    if added:
        await update.message.reply_text(f"✅ Tracking token(s):\n" + "\n".join(added))
    if skipped:
        await update.message.reply_text(f"ℹ️ Already tracked:\n" + "\n".join(skipped))


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ...")
        return

    removed = []
    not_found = []

    for address in addresses:
        if address in TRACKED_TOKENS:
            TRACKED_TOKENS.remove(address)
            removed.append(address)
        else:
            not_found.append(address)

    save_tracked_tokens()

    if removed:
        await update.message.reply_text(f"🗑️ Removed token(s):\n" + "\n".join(removed))
    if not_found:
        await update.message.reply_text(f"❌ Address(es) not found:\n" + "\n".join(not_found))



async def list_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not TRACKED_TOKENS:
        await update.message.reply_text("📭 No tokens being tracked.")
        return

    msg = "📊 Tracked Tokens:\n"

    for addr in TRACKED_TOKENS:
        symbol = ADDRESS_TO_SYMBOL.get(addr, addr[:6] + "...")
        link = f"[{symbol}]({BASE_URL}{addr})"

        # Get latest market cap from cached data
        history = TOKEN_DATA_HISTORY.get(addr, [])
        market_cap = history[0].get("marketCap") if history else None
        mc_text = f" - Market Cap: ${market_cap:,.0f}" if market_cap else ""

        msg += f"- {link} ({addr[:6]}...{addr[-4:]}){mc_text}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    TRACKED_TOKENS.clear()
    ADDRESS_TO_SYMBOL.clear()
    TOKEN_DATA_HISTORY.clear()
    LAST_SAVED_HASHES.clear()

    save_tracked_tokens()
    save_symbols_to_file()
    save_token_history()
    await update.message.reply_text("🔄 All tracked data (tokens, symbols, history) has been cleared.")


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

                        if any(p >= 15 for p in recent_changes):
                            link = f"[{cleaned_data['symbol']}]({BASE_URL}{address})"
                            msg = (
                                f"📢 {link} is spiking!\n"
                                f"5m Change: {cleaned_data['priceChange_m5']}%\n"
                                f"5m Volume: ${cleaned_data['volume_m5']:,.2f}\n"
                                f"Market Cap: ${cleaned_data['marketCap']:,.0f}"
                            )
                            await send_message(app.bot, msg, parse_mode="Markdown")

            if save_needed:
                await asyncio.to_thread(save_token_history)

            await asyncio.sleep(POLL_INTERVAL)

    return monitor()


# --- Bot Runner ---
def main():
    load_symbols_from_file()
    load_token_history()  # ✅ Restore TOKEN_DATA_HISTORY and LAST_SAVED_HASHES
    load_tracked_tokens()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_tokens))
    app.add_handler(CommandHandler("reset", reset))

    app.run_polling()

if __name__ == "__main__":
    main()
