import asyncio
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Set, Tuple, Any

from config import POLL_INTERVAL, SUPER_ADMIN_ID, BOT_SPIKE_LOGS_ID
from admin import ADMINS

import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
import storage.history as history
import storage.thresholds as thresholds

from api import fetch_prices_for_tokens
from util.utils import chunked, send_message

from storage.notify import build_normal_spike_message, build_first_spike_message

logger = logging.getLogger(__name__)

class TokenPriceMonitor:
    """
    Class to handle batch monitoring and processing of token prices
    with optimized data handling and notifications.
    """
    
    def __init__(self, app, chunk_size=30, notification_batch_size=20, 
                 max_concurrent_notifications=5):
        """
        Initialize the token price monitor.
        
        Args:
            app: The application instance with the bot
            chunk_size: Maximum tokens to include in an API request
            notification_batch_size: How many notifications to process in a batch
            max_concurrent_notifications: Maximum concurrent notification tasks
        """
        self.app = app
        self.chunk_size = chunk_size
        self.notification_batch_size = notification_batch_size
        self.max_concurrent_notifications = max_concurrent_notifications
        # Semaphore to control concurrent notifications
        self.notification_semaphore = asyncio.Semaphore(max_concurrent_notifications)
        
    async def collect_active_tokens(self) -> Set[str]:
        """Collect all unique tokens being tracked by active users."""
        active_tokens = set()
        
        for chat_id, tokens_list in users.USER_TRACKING.items():
            if users.USER_STATUS.get(chat_id) and tokens_list:
                active_tokens.update(tokens_list)
                
        return active_tokens
    
    async def fetch_token_data(self, active_tokens: Set[str]) -> Tuple[List[Dict], bool]:
        """
        Fetch token data in optimized batches.
        
        Args:
            active_tokens: Set of token addresses to fetch data for
            
        Returns:
            Tuple of (all_token_data, save_needed)
        """
        all_token_data = []
        save_needed = False
        
        # Process empty list early
        if not active_tokens:
            return all_token_data, save_needed
        
        # Process tokens in chunks for API efficiency
        for chunk in chunked(sorted(active_tokens), self.chunk_size):
            token_data_list = fetch_prices_for_tokens(chunk)
            
            if not token_data_list:
                logger.warning("⚠️ No token data returned from API — skipping chunk.")
                continue
                
            # Process and store token data
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
                    
                    if address not in history.TOKEN_DATA_HISTORY:
                        history.TOKEN_DATA_HISTORY[address] = []
                    history.TOKEN_DATA_HISTORY[address].insert(0, cleaned_data)
                    history_data = history.TOKEN_DATA_HISTORY[address]
                    history.TOKEN_DATA_HISTORY[address] = history_data[:3]

                    tokens.ACTIVE_TOKEN_DATA[address] = tokens.ACTIVE_TOKEN_DATA.get(address, [])
                    tokens.ACTIVE_TOKEN_DATA[address].insert(0, cleaned_data)
                    tokens.ACTIVE_TOKEN_DATA[address] = tokens.ACTIVE_TOKEN_DATA[address][:3]

                    save_needed = True
                    
                    # Add to processed results
                    all_token_data.append((address, cleaned_data))
        
        return all_token_data, save_needed

    async def process_spikes_and_notify(self, token_data_list: List[Tuple[str, Dict]]):
        """
        Process price spikes and send notifications in batches.
        
        Args:
            token_data_list: List of (address, data) tuples to process
        """
        # Group notifications by user for batching
        user_notifications = {}  # {user_id: [(address, cleaned_data, spike_type), ...]}
        admin_notifications = []
        
        # First pass: identify all notifications needed
        for address, cleaned_data in token_data_list:
            history_data = history.TOKEN_DATA_HISTORY.get(address, [])[:3]
            recent_changes = [
                entry.get("priceChange_m5")
                for entry in history_data
                if isinstance(entry.get("priceChange_m5"), (int, float))
            ]

            change = cleaned_data.get("priceChange_m5")
            timestamp = cleaned_data.get("timestamp")
            
            if not isinstance(change, (int, float)):
                continue
                
            # Check which users need notifications for this token
            for chat_id, tokens_list in users.USER_TRACKING.items():
                if users.USER_STATUS.get(chat_id) and address in tokens_list:
                    threshold_value = thresholds.USER_THRESHOLDS.get(chat_id, 5.0)

                    if change >= threshold_value:
                        minutes_per_period = 5
                        # First spike detection
                        if not any(p >= threshold_value for p in recent_changes[1:]):
                            minutes = minutes_per_period
                            spike_type = "first"
                            spike_type_for_user = f"🚀 First spike detected in the last {minutes} minutes!"
                        else:
                            # Ongoing spike detection
                            furthest_spike_idx = None
                            for idx, p in enumerate(recent_changes[1:], start=1):
                                if p >= threshold_value:
                                    furthest_spike_idx = idx
                            total_periods = (furthest_spike_idx + 1) if furthest_spike_idx is not None else 1
                            minutes = total_periods * minutes_per_period
                            spike_type = "ongoing"
                            spike_type_for_user = f"📈 Ongoing spike sustained over {minutes} minutes!"

                        # Group notifications by user
                        if chat_id not in user_notifications:
                            user_notifications[chat_id] = []
                        
                        user_notifications[chat_id].append((address, cleaned_data, spike_type, 
                                                           spike_type_for_user, timestamp))
        
        # Process notifications in batches
        notification_tasks = []
        
        # Create tasks for user notifications
        for chat_id, notifications in user_notifications.items():
            notification_tasks.append(
                self._send_user_notifications_batch(chat_id, notifications)
            )
            
            # For admin log
            for address, cleaned_data, spike_type, spike_type_for_user, timestamp in notifications:
                try:
                    chat = await self.app.bot.get_chat(chat_id)
                    user_name = f"@{chat.username}" if chat.username else chat.full_name
                except Exception:
                    user_name = f"User {chat_id}"
                
                admin_notifications.append((chat_id, user_name, address, cleaned_data, 
                                           spike_type, spike_type_for_user, timestamp))
        
        # Create tasks for admin notifications
        for i in range(0, len(admin_notifications), self.notification_batch_size):
            batch = admin_notifications[i:i+self.notification_batch_size]
            notification_tasks.append(
                self._send_admin_notifications_batch(batch)
            )
        
        # Execute all notification tasks concurrently
        if notification_tasks:
            await asyncio.gather(*notification_tasks)
            
    async def _send_user_notifications_batch(self, chat_id: int, 
                                           notifications: List[Tuple[str, Dict, str, str, str]]):
        """Send a batch of notifications to a single user."""
        async with self.notification_semaphore:
            for address, cleaned_data, spike_type, spike_type_for_user, timestamp in notifications:
                try:
                    # Build appropriate message
                    if spike_type == "first":
                        msg = await build_first_spike_message(cleaned_data, address, timestamp)
                    else:
                        msg = await build_normal_spike_message(cleaned_data, address, timestamp)
                    
                    msg = f"{spike_type_for_user}\n\n{msg}"
                    
                    # Send notification to user
                    await send_message(
                        self.app.bot,
                        msg,
                        chat_id=chat_id,
                        parse_mode="Markdown",
                        admins=ADMINS,
                        super_admin=SUPER_ADMIN_ID
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to user {chat_id}: {str(e)}")
    
    async def _send_admin_notifications_batch(self, notifications: List[Tuple]):
        """Send a batch of notifications to admin log."""
        async with self.notification_semaphore:
            for chat_id, user_name, address, cleaned_data, spike_type, spike_type_for_user, timestamp in notifications:
                try:
                    # Build appropriate message
                    if spike_type == "first":
                        msg = await build_first_spike_message(cleaned_data, address, timestamp)
                    else:
                        msg = await build_normal_spike_message(cleaned_data, address, timestamp)
                    
                    msg = f"{spike_type_for_user}\n\n{msg}"
                    
                    admin_msg = (
                        f"🔔 [User Alert from {user_name}]\n\n"
                        f"{msg}"
                    )
                    
                    # Send notification to admin log
                    await send_message(
                        self.app.bot,
                        admin_msg,
                        chat_id=BOT_SPIKE_LOGS_ID,
                        parse_mode="Markdown",
                        admins=ADMINS,
                        super_admin=SUPER_ADMIN_ID
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to admin log: {str(e)}")
    
    async def cleanup_unused_tokens(self, active_tokens: Set[str]):
        """Clean up data for tokens that are no longer being tracked."""
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
    
    async def run_monitoring_cycle(self):
        """Run a single monitoring cycle with optimized batch processing."""
        try:
            # 1. Collect active tokens
            active_tokens = await self.collect_active_tokens()
            
            # 2. Fetch and process token data in batches
            token_data_list, save_needed = await self.fetch_token_data(active_tokens)
            
            # 3. Process spikes and send notifications
            await self.process_spikes_and_notify(token_data_list)
            
            # 4. Clean up unused tokens
            await self.cleanup_unused_tokens(active_tokens)
            
            # 5. Save data if needed
            if save_needed:
                logger.debug("[MONITOR] Changes detected. Saving token history and active tokens...")
                await asyncio.to_thread(tokens.save_active_token_data)
                await asyncio.to_thread(history.save_token_history)
            else:
                logger.debug("[MONITOR] No changes detected. Skipping save operations.")
                
            return True
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {str(e)}")
            return False


def background_price_monitor(app):
    """
    Create a background task to monitor prices at regular intervals.
    
    Args:
        app: The application instance with the bot
    """
    async def monitor():
        try:
            monitor = TokenPriceMonitor(
                app, 
                chunk_size=30,
                notification_batch_size=20,
                max_concurrent_notifications=5
            )
            
            while True:
                await monitor.run_monitoring_cycle()
                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("🛑 Monitor task cancelled cleanly.")

    return monitor()