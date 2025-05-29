import asyncio
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Set, Tuple, Any

from config import POLL_INTERVAL, SUPER_ADMIN_ID, BOT_SPIKE_LOGS_ID

import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
import storage.history as history
import storage.thresholds as thresholds
import storage.notify as notify

from api import fetch_prices_for_tokens
from util.utils import chunked, send_message

from storage.notify import build_normal_spike_message, build_first_spike_message, save_user_notify_entry
import storage.admin_collection as admins

logger = logging.getLogger(__name__)

class TokenPriceMonitor:
    """
    Class to handle batch monitoring and processing of token prices
    with optimized data handling and notifications.
    """
    
    def __init__(self, app, chunk_size=30, notification_batch_size=20, 
                 max_concurrent_notifications=5, save_threshold=50, 
                 max_save_delay=5):
        """
        Initialize the token price monitor.
        
        Args:
            app: The application instance with the bot
            chunk_size: Maximum tokens to include in an API request
            notification_batch_size: How many notifications to process in a batch
            max_concurrent_notifications: Maximum concurrent notification tasks
            save_threshold: Number of changes to accumulate before saving
            max_save_delay: Maximum cycles to wait before forcing a save
        """
        self.app = app
        self.chunk_size = chunk_size
        self.notification_batch_size = notification_batch_size
        self.max_concurrent_notifications = max_concurrent_notifications
        # Semaphore to control concurrent notifications
        self.notification_semaphore = asyncio.Semaphore(max_concurrent_notifications)
        
        # Save batching parameters
        self.save_threshold = save_threshold
        self.max_save_delay = max_save_delay
        self.pending_changes = 0
        self.cycles_since_last_save = 0

        # Track whether we're in startup phase
        self.is_first_run = True
        
    async def collect_active_tokens(self) -> List[Dict[str, str]]:
        """
        Collect all unique tokens being tracked by active users.
        
        Returns:
            List of dicts with 'chain_id' and 'address' for each unique active token.
        """
        active_tokens = []
        seen_tokens = set()  # Use a set to track unique tokens we've already added
        
        for chat_id, user_chains in users.USER_TRACKING.items():
            # Skip inactive users
            if not users.USER_STATUS.get(chat_id):
                continue
                
            # Process each chain and its addresses
            for chain_id, addresses in user_chains.items():
                if not isinstance(addresses, list):
                    continue
                    
                # Process each address in this chain
                for address in addresses:
                    # Create a unique key for this token
                    token_key = f"{chain_id}:{address}"
                    
                    # Only add if we haven't seen this token before
                    if token_key not in seen_tokens:
                        active_tokens.append({
                            'chain_id': chain_id,
                            'address': address
                        })
                        seen_tokens.add(token_key)
        
        return active_tokens

    async def fetch_token_data(self, active_tokens: List[Dict]) -> Tuple[List[Dict], int]:
        """
        Fetch token data in optimized batches.
        
        Args:
            active_tokens: List of token dicts with chain_id and address
                
        Returns:
            Tuple of (all_token_data, change_count)
        """
        all_token_data = []
        change_count = 0
        startup_loaded_count = 0
        
        # Process empty list early
        if not active_tokens:
            return all_token_data, change_count
        
        # Process tokens in chunks for API efficiency
        # First sort by chain_id to optimize batching
        active_tokens.sort(key=lambda x: x.get('chain_id', ''))
        
        for chunk in chunked(active_tokens, self.chunk_size):
            token_data_list = await fetch_prices_for_tokens(chunk)
            #token_data_list = await asyncio.to_thread(fetch_prices_for_tokens, chunk)

            
            if not token_data_list:
                logger.warning("⚠️ No token data returned from API — skipping chunk.")
                continue
                
            # Process and store token data
            for data in token_data_list:
                base = data.get("baseToken", {})
                address = base.get("address")
                chain_id = data.get("chainId")
                
                if not address or not chain_id:
                    continue

                # Use chain_id+address as the unique identifier
                #token_key = f"{chain_id}:{address}"
                
                if address not in symbols.ADDRESS_TO_SYMBOL:
                    symbol = base.get("symbol", address[:6])
                    symbols.ADDRESS_TO_SYMBOL[address] = symbol
                    
                symbol = symbols.ADDRESS_TO_SYMBOL.get(address)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                cleaned_data = {
                    "timestamp": timestamp,
                    "address": address,
                    "symbol": symbol,
                    "chain_id": chain_id,
                    "priceChange_m5": data.get("priceChange", {}).get("m5"),
                    "volume_m5": data.get("volume", {}).get("m5"),
                    "marketCap": data.get("marketCap")
                }

                # Use the optimized history module to check for changes
                if history.update_token_data(address, cleaned_data):
                    # Data was updated, update the active token data as well
                    if address not in history.ACTIVE_TOKEN_DATA:
                        history.ACTIVE_TOKEN_DATA[address] = []
                    
                    history.ACTIVE_TOKEN_DATA[address].insert(0, cleaned_data)
                    history.ACTIVE_TOKEN_DATA[address] = history.ACTIVE_TOKEN_DATA[address][:3]
                    
                    # Only count changes after startup is complete
                    if not self.is_first_run:
                        change_count += 1
                    
                    # Add to processed results for notifications
                    all_token_data.append((address, cleaned_data))
                else:
                    # Data was unchanged
                    if self.is_first_run:
                        startup_loaded_count += 1

        if self.is_first_run:
            logger.info(f"[STARTUP] Loaded {startup_loaded_count} tokens with unchanged data")
            self.is_first_run = False

        return all_token_data, change_count


    async def process_spikes_and_notify(self, token_data_list: List[Tuple[str, Dict]]):
        """
        Process price spikes and send notifications in batches.
        
        Args:
            token_data_list: List of (token_key, data) tuples to process
        """
        # Group notifications by user for batching
        user_notifications = {}  # {user_id: [(token_key, cleaned_data, spike_type), ...]}
        admin_notifications = []
        
        # First pass: identify all notifications needed
        for address, cleaned_data in token_data_list:
            #history_data = history.TOKEN_DATA_HISTORY.get(address, [])[:3] #changed this to use ACTIVE_TOKEN_DATA
            history_data = history.ACTIVE_TOKEN_DATA.get(address, [])[:3]
            recent_changes = [
                entry.get("priceChange_m5")
                for entry in history_data
                if isinstance(entry.get("priceChange_m5"), (int, float))
            ]

            change = cleaned_data.get("priceChange_m5")
            timestamp = cleaned_data.get("timestamp")
            chain_id = cleaned_data.get("chain_id")
            
            
            if not isinstance(change, (int, float)):
                continue
                
            # Check which users need notifications for this token
            for chat_id, user_chains in users.USER_TRACKING.items():
                if not users.USER_STATUS.get(chat_id):
                    continue
                    
                # Check if this user is tracking this token
                addresses_for_chain = user_chains.get(chain_id, [])
                if address in addresses_for_chain:
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

        # Marking users who got spike alerts
        now_iso = datetime.now().isoformat()
        notify_updates = []
        
        # Create tasks for user notifications
        for chat_id, notifications in user_notifications.items():
            notification_tasks.append(
                self._send_user_notifications_batch(chat_id, notifications)
            )

            # Update notify cache (only memory, not Mongo yet)
            notify_updates.append((chat_id, {
                "last_alert_time": now_iso,
                "next_interval": 24,
                "has_received_spike": True
            }))

            
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
        
        # In-memory notify update only
        if notify_updates:
            await save_user_notify_entry(notify_updates)
            
    async def _send_user_notifications_batch(self, chat_id: int, 
                                           notifications: List[Tuple[str, Dict, str, str, str]]):
        """Send a batch of notifications to a single user."""
        async with self.notification_semaphore:
            for token_key, cleaned_data, spike_type, spike_type_for_user, timestamp in notifications:
                try:
                    chain_id = cleaned_data.get("chain_id")
                    address = cleaned_data.get("address")
                    chain_id = chain_id.capitalize()
                    
                    # Build appropriate message
                    if spike_type == "first":
                        msg = await build_first_spike_message(cleaned_data, address, timestamp)
                    else:
                        msg = await build_normal_spike_message(cleaned_data, address, timestamp)
                    
                    # Add chain info to the message
                    msg = f"{spike_type_for_user}\n\n🔗 Chain: {chain_id}\n\n{msg}"
                    
                    # Send notification to user
                    await send_message(
                        self.app.bot,
                        msg,
                        chat_id=chat_id,
                        parse_mode="Markdown",
                        admins=admins.ADMINS,
                        super_admin=SUPER_ADMIN_ID,
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to user {chat_id}: {str(e)}")
    
    async def _send_admin_notifications_batch(self, notifications: List[Tuple]):
        """Send a batch of notifications to admin log."""
        async with self.notification_semaphore:
            for chat_id, user_name, token_key, cleaned_data, spike_type, spike_type_for_user, timestamp in notifications:
                try:
                    chain_id = cleaned_data.get("chain_id")
                    address = cleaned_data.get("address")
                    chain_id = chain_id.capitalize()
                    
                    # Build appropriate message
                    if spike_type == "first":
                        msg = await build_first_spike_message(cleaned_data, address, timestamp)
                    else:
                        msg = await build_normal_spike_message(cleaned_data, address, timestamp)
                    
                    # Add chain info to the message
                    msg = f"{spike_type_for_user}\n🔗 Chain: {chain_id}\n\n{msg}"
                    
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
                        admins=admins.ADMINS,
                        super_admin=SUPER_ADMIN_ID,
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to admin log: {str(e)}")
    
    async def cleanup_unused_tokens(self, active_tokens: List[Dict[str, str]]):
        """Clean up token data for addresses no longer tracked by active users."""
        
        # Set of active addresses (from active users)
        active_addresses = {t["address"] for t in active_tokens}
        
        # Get all tokens being tracked from TRACKED_TOKEN
        all_tracked_addresses = {
            address
            for chain_tokens in tokens.TRACKED_TOKENS.values()
            for address in chain_tokens
        }

        # Clean up stale token history and active data based on address keys
        for address in list(history.TOKEN_DATA_HISTORY.keys()):
            if address not in all_tracked_addresses:
                history.TOKEN_DATA_HISTORY.pop(address, None)
                history.ACTIVE_TOKEN_DATA.pop(address, None)
                history.LAST_SAVED_HASHES.pop(address, None)
                symbols.ADDRESS_TO_SYMBOL.pop(address, None)
                for chain in list(tokens.TRACKED_TOKENS):
                    if address in tokens.TRACKED_TOKENS[chain]:
                        tokens.TRACKED_TOKENS[chain].remove(address)

        # Clean up orphaned active data (no longer active for this cycle)
        for address in list(history.ACTIVE_TOKEN_DATA):
            if address not in active_addresses:
                history.ACTIVE_TOKEN_DATA.pop(address, None)

    
    async def save_data_if_needed(self, change_count: int, force_save=False):
        """
        Save data if the changes exceed threshold, max delay is reached, or forced.
        
        Args:
            change_count: Number of changes detected in this cycle
            force_save: Force a save regardless of thresholds
        """
        self.pending_changes += change_count
        self.cycles_since_last_save += 1
        
        need_to_save = (
            force_save or
            (self.pending_changes >= self.save_threshold) or
            (self.cycles_since_last_save >= self.max_save_delay and self.pending_changes > 0)
        )
        
        if need_to_save:
            logger.info(
                f"[MONITOR] Saving data: {self.pending_changes} changes after {self.cycles_since_last_save} cycles"
            )
            
            async with asyncio.TaskGroup() as tg:
                tg.create_task(history.save_token_history())

            # Reset counters
            self.pending_changes = 0
            self.cycles_since_last_save = 0
            return True
        else:
            logger.debug(
                f"[MONITOR] Deferring save: {self.pending_changes}/{self.save_threshold} changes, "
                f"{self.cycles_since_last_save}/{self.max_save_delay} cycles"
            )
            return False
    
    async def run_monitoring_cycle(self):
        """Run a single monitoring cycle with optimized batch processing."""
        try:
            # 1. Collect active tokens
            active_tokens = await self.collect_active_tokens()
            
            # 2. Fetch and process token data in batches
            token_data_list, change_count = await self.fetch_token_data(active_tokens)
            
            # 3. Process spikes and send notifications
            await self.process_spikes_and_notify(token_data_list)
            
            # 4. Clean up unused tokens
            await self.cleanup_unused_tokens(active_tokens)
            
            # 5. Save data if threshold reached or max delay exceeded
            if change_count > 0:
                # Force a save if this is a complete cycle
                # This ensures data is saved at least once per monitoring cycle if there were changes
                force_save = False  # We're forcing a save at the end of each cycle with changes
                await self.save_data_if_needed(change_count, force_save)
                
            return True
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {str(e)}")
            return False


def background_price_monitor(app):
    """
    Create a background task to monitor prices at regular intervals.
    """
    async def monitor():
        monitor = TokenPriceMonitor(
            app,
            chunk_size=30,
            notification_batch_size=20,
            max_concurrent_notifications=5,
            save_threshold=50, # Save after 50 changes
            max_save_delay=5   # Or after 5 cycles with pending changes
        )

        running = False

        try:
            while True:
                if not running:
                    running = True

                    async def cycle_wrapper():
                        nonlocal running
                        try:
                            await monitor.run_monitoring_cycle()
                        except Exception as e:
                            logger.error(f"[MONITOR] Cycle error: {e}")
                        finally:
                            running = False

                    asyncio.create_task(cycle_wrapper())

                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("🛑 Monitor task cancelled cleanly.")
            if monitor.pending_changes > 0:
                logger.info(f"[MONITOR] Saving {monitor.pending_changes} pending changes before exit")
                #await asyncio.to_thread(tokens.save_active_token_data)
                await history.save_token_history()

    return monitor()
