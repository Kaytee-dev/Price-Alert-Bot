import asyncio
import json
import hashlib
import logging
from datetime import datetime

from config import POLL_INTERVAL, SUPER_ADMIN_ID, BOT_LOGS_ID
from admin import ADMINS

import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
import storage.history as history
import storage.thresholds as thresholds

from api import fetch_prices_for_tokens
from utils import chunked, send_message

from storage.notify import build_normal_spike_message, build_first_spike_message



def background_price_monitor(app):
    async def monitor():
        try:
            while True:
                save_needed = False
                active_tokens = set()

                for chat_id, tokens_list in users.USER_TRACKING.items():
                    if users.USER_STATUS.get(chat_id) and tokens_list:
                        active_tokens.update(tokens_list)


                if active_tokens:
                    for chunk in chunked(sorted(active_tokens), 30):
                        token_data_list = fetch_prices_for_tokens(chunk)

                        if not token_data_list:
                            logging.warning("⚠️ No token data returned from API — skipping chunk.")
                            continue  # Skip processing
                        
                        for data in token_data_list:
                            base = data.get("baseToken", {})
                            address = base.get("address")
                            if not address:
                                continue

                            if address not in symbols.ADDRESS_TO_SYMBOL:
                                symbol = base.get("symbol", address[:6])
                                symbols.ADDRESS_TO_SYMBOL[address] = symbol
                                symbols.save_symbols_to_file()

                            symbol = symbols.ADDRESS_TO_SYMBOL.get(address)
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            cleaned_data = {
                                "timestamp": timestamp,
                                "address": address,
                                "symbol": symbol,
                                "priceChange_m5": data.get("priceChange", {}).get("m5"),
                                "volume_m5": data.get("volume", {}).get("m5"),
                                "marketCap": data.get("marketCap")
                            }

                            if address not in history.TOKEN_DATA_HISTORY:
                                history.TOKEN_DATA_HISTORY[address] = []
                            history.TOKEN_DATA_HISTORY[address].insert(0, cleaned_data)
                            hist_data = history.TOKEN_DATA_HISTORY[address]
                            
                            logging.debug("📊 First 3 history entries:\n%s", json.dumps(hist_data[:3], indent=2)[:500])
                            history.TOKEN_DATA_HISTORY[address] = history.TOKEN_DATA_HISTORY[address][:3]

                            tokens.ACTIVE_TOKEN_DATA[address] = tokens.ACTIVE_TOKEN_DATA.get(address, [])
                            tokens.ACTIVE_TOKEN_DATA[address].insert(0, cleaned_data)
                            tokens.ACTIVE_TOKEN_DATA[address] = tokens.ACTIVE_TOKEN_DATA[address][:3]

                            hash_base = {
                                "address": cleaned_data["address"],
                                "symbol": cleaned_data["symbol"],
                                "priceChange_m5": cleaned_data["priceChange_m5"],
                                "volume_m5": cleaned_data["volume_m5"],
                                "marketCap": cleaned_data["marketCap"]
                            }

                            snapshot_json = json.dumps(hash_base, sort_keys=True)
                            hash_val = hashlib.md5(snapshot_json.encode()).hexdigest()

                            if history.LAST_SAVED_HASHES.get(address) != hash_val:
                                history.LAST_SAVED_HASHES[address] = hash_val
                                save_needed = True

                            history_data = history.TOKEN_DATA_HISTORY[address][:3]
                            recent_changes = [
                                entry.get("priceChange_m5")
                                for entry in history_data
                                if isinstance(entry.get("priceChange_m5"), (int, float))
                            ]

                            change = cleaned_data.get("priceChange_m5")
                            notified_users = set()
                            first_time_spike_users = set()
                            user_alert_messages = {}

                            for chat_id, tokens_list in users.USER_TRACKING.items():
                                if users.USER_STATUS.get(chat_id) and address in tokens_list:
                                    threshold_value = thresholds.USER_THRESHOLDS.get(chat_id, 5.0)

                                    if isinstance(change, (int, float)) and change >= threshold_value:
                                        minutes_per_period = 5
                                        if not any(p >= threshold_value for p in recent_changes[1:]):
                                            minutes = minutes_per_period
                                            msg = await build_first_spike_message(cleaned_data, address, timestamp)
                                            first_time_spike_users.add(chat_id)
                                            spike_type_for_user = f"🚀 First spike detected in the last {minutes} minutes!"
                                        else:
                                            furthest_spike_idx = None
                                            for idx, p in enumerate(recent_changes[1:], start=1):
                                                if p >= threshold_value:
                                                    furthest_spike_idx = idx
                                            total_periods = (furthest_spike_idx + 1) if furthest_spike_idx is not None else 1
                                            minutes = total_periods * minutes_per_period
                                            msg = await build_normal_spike_message(cleaned_data, address, timestamp)
                                            spike_type_for_user = f"📈 Ongoing spike sustained over {minutes} minutes!"

                                        msg = f"{spike_type_for_user}\n\n{msg}"

                                        await send_message(
                                            app.bot,
                                            msg,
                                            chat_id=chat_id,
                                            parse_mode="Markdown",
                                            admins=ADMINS,
                                            super_admin=SUPER_ADMIN_ID
                                        )
                                        notified_users.add(chat_id)
                                        user_alert_messages[chat_id] = msg

                            for user_id in notified_users:
                                try:
                                    chat = await app.bot.get_chat(user_id)
                                    user_name = f"@{chat.username}" if chat.username else chat.full_name
                                except Exception:
                                    user_name = f"User {user_id}"


                                admin_msg = (
                                    f"🔔 [User Alert from {user_name}]\n\n"
                                    f"{user_alert_messages[user_id]}"
                                )

                                await send_message(
                                    app.bot,
                                    admin_msg,
                                    chat_id=BOT_LOGS_ID,
                                    parse_mode="Markdown",
                                    admins=ADMINS,
                                    super_admin=SUPER_ADMIN_ID
                                )




                all_tracked_tokens = set(addr for tokens_list in users.USER_TRACKING.values() for addr in tokens_list)
                for token in list(history.TOKEN_DATA_HISTORY.keys()):
                    if token not in all_tracked_tokens:
                        history.TOKEN_DATA_HISTORY.pop(token, None)
                        tokens.ACTIVE_TOKEN_DATA.pop(token, None)
                        history.LAST_SAVED_HASHES.pop(token, None)
                        symbols.ADDRESS_TO_SYMBOL.pop(token, None)
                        if token in tokens.TRACKED_TOKENS:
                            tokens.TRACKED_TOKENS.remove(token)

                for token in list(tokens.ACTIVE_TOKEN_DATA):
                    if token not in active_tokens:
                        tokens.ACTIVE_TOKEN_DATA.pop(token, None)

                if save_needed:
                    logging.debug("[MONITOR] Changes detected. Saving token history and active tokens...")
                    await asyncio.to_thread(tokens.save_active_token_data)
                    await asyncio.to_thread(history.save_token_history)

                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logging.info("🛑 Monitor task cancelled cleanly.")

    return monitor()
