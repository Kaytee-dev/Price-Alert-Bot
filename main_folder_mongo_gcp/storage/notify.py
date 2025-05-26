# notify.py
import logging
import asyncio
from datetime import datetime
from config import DEXSCREENER_BASE
from util.utils import send_message
from storage import users
from mongo_client import get_collection
from typing import List, Tuple
from pymongo import UpdateOne

USER_NOTIFY_CACHE = {}
USER_NOTIFY_COLLECTION = {}

logger = logging.getLogger(__name__)


def get_notify_collection():
    return get_collection("user_notify")


async def load_user_notify_cache():
    """
    Load all notify data into memory from MongoDB.
    """
    global USER_NOTIFY_CACHE
    collection = get_notify_collection()
    cursor = collection.find({})
    USER_NOTIFY_CACHE = {
        doc["_id"]: {
            "last_alert_time": doc.get("last_alert_time"),
            "next_interval": doc.get("next_interval", 24)
        }
        async for doc in cursor
    }


async def save_user_notify_entry(entries: List[Tuple[str | int, dict]]):
    """
    Update in-memory cache only. Use flush_notify_cache_to_db() to persist later.
    """
    global USER_NOTIFY_CACHE

    for chat_id, data in entries:
        USER_NOTIFY_CACHE[str(chat_id)] = data


async def build_normal_spike_message(cleaned_data, address, timestamp):
    base_url = f"{DEXSCREENER_BASE}{cleaned_data['chain_id']}/"
    link = f"[{cleaned_data['symbol']}]({base_url}{address})"
    message = (
        f"📢 {link} is spiking!\n"
        f"🪙 `{cleaned_data['address']}`\n\n"
        f"💰 Market Cap: ${cleaned_data['marketCap']:,.0f}\n\n"
        f"💹 5m Change: {cleaned_data['priceChange_m5']}%\n"
        f"📈 5m Volume: ${cleaned_data['volume_m5']:,.2f}\n\n"
        f"🕓 Timestamps: {timestamp}\n"
    )
    return message


async def build_first_spike_message(cleaned_data, address, timestamp):
    base_url = f"{DEXSCREENER_BASE}{cleaned_data['chain_id']}/"
    link = f"[{cleaned_data['symbol']}]({base_url}{address})"
    message = (
        f"📢 {link} is spiking!\n"
        f"🪙 `{cleaned_data['address']}`\n\n"
        f"💰 Market Cap: ${cleaned_data['marketCap']:,.0f}\n\n"
        f"💹 5m Change: {cleaned_data['priceChange_m5']}%\n"
        f"📈 5m Volume: ${cleaned_data['volume_m5']:,.2f}\n"
        f"🕓 Timestamps: {timestamp}\n\n"
        f"👀 *Keep eyes peeled — Early spike detected!*"
    )
    return message


async def remind_inactive_users(app):
    if not USER_NOTIFY_CACHE:
        await load_user_notify_cache()

    while True:
        for chat_id, tracking_list in users.USER_TRACKING.items():
            if not users.USER_STATUS.get(chat_id) or not tracking_list:
                continue

            chat_id_str = str(chat_id)
            user_data = USER_NOTIFY_CACHE.get(chat_id_str)

            # If user has no entry, initialize in memory
            if not user_data:
                USER_NOTIFY_CACHE[chat_id_str] = {
                    "last_alert_time": datetime.now().isoformat(),
                    "next_interval": 24,
                    "has_received_spike": False
                }
                continue  # wait until next interval

            # Skip users who already got a spike
            if user_data.get("has_received_spike", False):
                continue

            # Check if it's time for a reminder
            last_alert = datetime.fromisoformat(user_data["last_alert_time"])
            hours_elapsed = (datetime.now() - last_alert).total_seconds() / 3600
            next_interval = user_data.get("next_interval", 24)

            if hours_elapsed >= next_interval:
                await send_message(
                    app.bot,
                    "👀 Your tokens are actively monitored. No spike alerts yet — stay tuned!",
                    chat_id=chat_id
                )

                # Update next interval and in-memory cache
                new_interval = {24: 36, 36: 48, 48: 24}.get(next_interval, 24)
                USER_NOTIFY_CACHE[chat_id_str] = {
                    "last_alert_time": datetime.now().isoformat(),
                    "next_interval": new_interval,
                    "has_received_spike": False
                }

        await asyncio.sleep(43200)  # Every 12 hours



async def ensure_notify_records_for_active_users():
    """
    At startup: load notify cache and ensure every active tracking user has an entry.
    """
    await load_user_notify_cache()

    new_entries = 0
    now_iso = datetime.now().isoformat()

    for chat_id, tracked in users.USER_TRACKING.items():
        if users.USER_STATUS.get(chat_id) and tracked:
            if str(chat_id) not in USER_NOTIFY_CACHE:
                USER_NOTIFY_CACHE[str(chat_id)] = {
                    "last_alert_time": now_iso,
                    "next_interval": 24,
                    "has_received_spike": False
                }
                new_entries += 1

    logger.info(f"🟢 Initialized {new_entries} user_notify records into memory.")


async def flush_notify_cache_to_db():
    """
    Writes all in-memory USER_NOTIFY_CACHE entries to MongoDB in bulk.
    """
    global USER_NOTIFY_CACHE
    if not USER_NOTIFY_CACHE:
        return

    collection = get_notify_collection()

    ops = [
        UpdateOne({"_id": uid}, {"$set": data}, upsert=True)
        for uid, data in USER_NOTIFY_CACHE.items()
    ]
    if ops:
        await collection.bulk_write(ops)
        logger.info(f"💾 Flushed {len(ops)} user_notify entries to MongoDB.")
