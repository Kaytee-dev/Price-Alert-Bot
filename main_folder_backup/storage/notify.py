import json
import asyncio
from datetime import datetime
from utils import load_json, save_json, send_message
from storage import users

from config import NOTIFY_DATA_FILE, BASE_URL


USER_NOTIFY_DATA = {}


def load_notify_data():
    global USER_NOTIFY_DATA
    USER_NOTIFY_DATA = load_json(NOTIFY_DATA_FILE, {}, "user notify data")


def save_notify_data():
    save_json(NOTIFY_DATA_FILE, USER_NOTIFY_DATA, "user notify data")


async def build_normal_spike_message(cleaned_data, address, timestamp):
    link = f"[{cleaned_data['symbol']}]({BASE_URL}{address})"
    message = (
        f"📢 {link} is spiking!\n\n"
        f"💰 Market Cap: ${cleaned_data['marketCap']:,.0f}\n\n"
        f"💹 5m Change: {cleaned_data['priceChange_m5']}%\n"
        f"📈 5m Volume: ${cleaned_data['volume_m5']:,.2f}\n\n"
        f"🕓 Timestamps: {timestamp}\n"
    )
    return message


async def build_first_spike_message(cleaned_data, address, timestamp):
    link = f"[{cleaned_data['symbol']}]({BASE_URL}{address})"
    message = (
        f"📢 {link} is spiking!\n\n"
        f"💰 Market Cap: ${cleaned_data['marketCap']:,.0f}\n\n"
        f"💹 5m Change: {cleaned_data['priceChange_m5']}%\n"
        f"📈 5m Volume: ${cleaned_data['volume_m5']:,.2f}\n"
        f"🕓 Timestamps: {timestamp}\n\n"
        f"👀 *Keep eyes peeled — Early spike detected!*"
    )
    return message


async def remind_inactive_users(app):
    while True:
        for chat_id, tracking_list in users.USER_TRACKING.items():
            if users.USER_STATUS.get(chat_id) and tracking_list:
                user_data = USER_NOTIFY_DATA.get(str(chat_id), {})
                last_alert_time_str = user_data.get("last_alert_time", datetime.now().isoformat())
                last_alert = datetime.fromisoformat(last_alert_time_str)
                next_interval = user_data.get("next_interval", 24)

                elapsed_hours = (datetime.now() - last_alert).total_seconds() / 3600

                if elapsed_hours >= next_interval:
                    await send_message(
                        app.bot,
                        "👀 Your tokens are actively monitored. No spike alerts yet — stay tuned!",
                        chat_id=chat_id
                    )

                    new_interval = {24: 36, 36: 48, 48: 24}.get(next_interval, 24)

                    USER_NOTIFY_DATA[str(chat_id)] = {
                        "last_alert_time": datetime.now().isoformat(),
                        "next_interval": new_interval
                    }
                    save_notify_data()
        await asyncio.sleep(3600)  # Check every hour
