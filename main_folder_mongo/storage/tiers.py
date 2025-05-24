# storage/tiers.py

import logging
import asyncio
from config import SUPER_ADMIN_ID
from util.utils import send_message
from util.get_all_tracked_tokens_util import get_all_tracked_tokens
from typing import Optional, Union
from telegram import Bot

from datetime import datetime

import storage.users as users
import storage.expiry as expiry
import storage.user_collection as user_collection

from pymongo import UpdateOne

logger = logging.getLogger(__name__)

FREE_LIMIT = 3
STANDARD_LIMIT = 10
PREMIUM_LIMIT = 20
OVERLORD_LIMIT = 40
SUPER_ADMIN_LIMIT = 999

TIER_LIMITS = {
    "apprentice": FREE_LIMIT,
    "disciple": STANDARD_LIMIT,
    "chieftain": PREMIUM_LIMIT,
    "overlord": OVERLORD_LIMIT,
    "super admin": SUPER_ADMIN_LIMIT,
}

USER_TIERS = {}  # {user_id: tier_name}

TIER_EXPIRY_CHECK_INTERVAL = 2 * 24 * 60 * 60 # 2 days
TIER_EXPIRY_ERROR_SLEEP = 1 * 60 * 60 # 1 hour


def get_user_tier(user_id: int) -> str:
    user_id_str = str(user_id)
    doc = user_collection.get_user(user_id_str)
    tier = doc.get("tier")
    if not tier:
        tier = "apprentice"
        doc["tier"] = tier
    return tier

def get_user_limit(user_id: int) -> int:
    if user_id == SUPER_ADMIN_ID:
        return SUPER_ADMIN_LIMIT
    tier = get_user_tier(user_id)
    return TIER_LIMITS.get(tier, FREE_LIMIT)

async def set_user_tier(user_id: int, tier: str, bot: Optional[Bot] = None):
    if tier not in TIER_LIMITS:
        raise ValueError("Invalid tier name")

    user_id_str = str(user_id)
    await user_collection.update_user_fields(user_id_str, {"tier": tier})
    logger.info(f"✯ Updated user {user_id} to tier '{tier}'")
    
    if bot:
        limit = get_user_limit(user_id)
        msg = f"🎯 Your tier has been updated to *{tier.capitalize()}*. You can now track up to {limit} token(s)."
        
        await send_message(bot, msg, chat_id=user_id)

def is_within_limit(user_id: int, token_count: int) -> bool:
    return token_count <= get_user_limit(user_id)

def delete_user_tier(user_id: int):
    user_id_str = str(user_id)
    if user_id_str in USER_TIERS:
        del USER_TIERS[user_id_str]
        

async def promote_to_premium(user_id: int, bot: Optional[Bot] = None):
    await set_user_tier(user_id, "chieftain", bot=bot)


async def trim_user_tokens_to_limit(user_id: Union[str, int], limit: int):
    user_id_str = str(user_id)
    user_chains = users.USER_TRACKING.get(user_id, {})
    all_tokens = get_all_tracked_tokens(user_id)

    if len(all_tokens) <= limit:
        return False

    trimmed_tokens = set(all_tokens[:limit])
    trimmed_count = len(set(all_tokens) - trimmed_tokens)
    new_tracking = {}
    

    for chain_id, addr_list in user_chains.items():
        new_list = [addr for addr in addr_list if addr in trimmed_tokens]
        if new_list:
            new_tracking[chain_id] = new_list
            
    users.USER_TRACKING[user_id] = new_tracking
    await users.overwrite_user_tracking(user_id_str, new_tracking)

    logger.info(f"🚫 Enforced token limit for user {user_id}. Trimmed {trimmed_count} token(s) to {limit} tokens.")
    return True


async def enforce_token_limit(user_id: int, bot: Optional[Bot] = None):
    user_id_str = str(user_id)

    if user_id == SUPER_ADMIN_ID:
        await user_collection.update_user_fields(user_id_str, {"tier": "super admin"})
        logger.info(f"🎯 Super admin tier enforced for user {user_id}")

    doc = user_collection.USER_COLLECTION.get(user_id_str, {})
    tier = doc.get("tier", "apprentice")
    allowed_limit = TIER_LIMITS.get(tier, FREE_LIMIT)

    trimmed = await trim_user_tokens_to_limit(user_id_str, allowed_limit)

    if trimmed and bot:
        await send_message(
            bot,
            f"🚫 Your tracked tokens exceeded your tier limit ({tier}). "
            f"So it has been trimmed it to the first {allowed_limit} token(s).",
            chat_id=user_id
        )

async def enforce_token_limits_bulk():
    """
    Enforce token limits for all users in bulk.
    """
    collection = user_collection.get_user_collection()
    bulk_operations = []
    user_tracking_updates = {}

    for user_id_str, user_chains in users.USER_TRACKING.items():
        user_id = int(user_id_str)

        # Get tier and limit
        user_doc = user_collection.USER_COLLECTION.get(user_id_str, {})
        tier = user_doc.get("tier", "apprentice")
        allowed_limit = TIER_LIMITS.get(tier, FREE_LIMIT)

        # Get tracked tokens and enforce limit
        all_tokens = get_all_tracked_tokens(user_id)
        if len(all_tokens) > allowed_limit:
            trimmed_tokens = set(all_tokens[:allowed_limit])
            new_tracking = {}

            for chain_id, addr_list in user_chains.items():
                new_list = [addr for addr in addr_list if addr in trimmed_tokens]
                if new_list:
                    new_tracking[chain_id] = new_list

            # Prepare MongoDB update
            bulk_operations.append(
                UpdateOne(
                    {"_id": user_id_str},
                    {"$set": {"tracking": new_tracking}},
                    upsert=True
                )
            )

            # Update in-memory tracking
            user_tracking_updates[user_id_str] = new_tracking

    # Execute bulk write if there are updates
    if bulk_operations:
        await collection.bulk_write(bulk_operations)

    # Update in-memory cache
    for user_id_str, new_tracking in user_tracking_updates.items():
        user_collection.USER_COLLECTION[user_id_str]["tracking"] = new_tracking
        users.USER_TRACKING[user_id_str] = new_tracking

    logger.info(f"✅ Enforced token limits for {len(bulk_operations)} users.")


def get_user_expiry(user_id: int) -> Optional[datetime]:
    user_id_str = str(user_id)
    expiry_str = user_collection.USER_COLLECTION.get(user_id_str, {}).get("expiry")
    if expiry_str:
        try:
            return datetime.fromisoformat(expiry_str)
        except ValueError:
            return None
    return None

async def set_user_expiry(user_id: int, expiry_date: datetime):
    user_id_str = str(user_id)
    expiry_str = expiry_date.isoformat()

    # Update in-memory
    user_collection.USER_COLLECTION.setdefault(user_id_str, {})["expiry"] = expiry_str

    # Persist to DB
    await user_collection.update_user_fields(user_id_str, {"expiry": expiry_str})

async def check_and_process_tier_expiry(bot: Bot):
    """
    Check for users with expiring tiers and process accordingly:
    - Send reminder 3 days before expiry
    - Send notice on expiry day
    - Downgrade after 3-day grace period
    
    Uses true batch processing to optimize performance and reduce API load
    """
    current_date = datetime.now()

    # Batch size for processing
    batch_size = 50
    user_ids = list(user_collection.USER_COLLECTION.keys())
    
    # Group users by action type to enable proper batching
    reminder_users = []      # 1-3 days before expiry
    expiry_today_users = []  # expiry day
    downgrade_users = []     # past grace period
    
    # First pass: categorize all users
    for i in range(0, len(user_ids), batch_size):
        batch_ids = user_ids[i:i+batch_size]

        for user_id_str in batch_ids:
            user_doc = user_collection.USER_COLLECTION[user_id_str]
            expiry_raw = user_doc.get("expiry")
            if not expiry_raw:
                continue

            try:
                expiry_date = datetime.fromisoformat(expiry_raw)
            except ValueError:
                continue

            user_id = int(user_id_str)
            days_until_expiry = (expiry_date - current_date).days
            grace_remaining = 3 + days_until_expiry

            user_tier = user_doc.get("tier", "apprentice")
            if user_tier == "apprentice":
                continue

            if days_until_expiry in (1, 2, 3):
                reminder_users.append((user_id, user_tier, days_until_expiry))
            elif days_until_expiry == 0:
                expiry_today_users.append((user_id, user_tier))
            elif grace_remaining <= 0:
                downgrade_users.append(user_id_str)
                    
        
    # Process reminders in batches
    logger.info(f"Processing {len(reminder_users)} users for expiry reminders")
    for i in range(0, len(reminder_users), batch_size):
        batch = reminder_users[i:i+batch_size]
        tasks = []
        
        for user_id, user_tier, days in batch:
            tasks.append(send_message(
                bot,
                f"⚠️ Your {user_tier.capitalize()} tier will expire in {days} days. " 
                f"Kindly renew your tier using /renew to keep your current benefits.",
                chat_id=user_id
            ))
            
        if tasks:
            # Execute batch of reminder messages concurrently
            await asyncio.gather(*tasks)
            logger.info(f"Sent expiry reminders to batch of {len(tasks)} users")
    
    # Process expiry day notifications in batches
    logger.info(f"Processing {len(expiry_today_users)} users for expiry day notifications")
    for i in range(0, len(expiry_today_users), batch_size):
        batch = expiry_today_users[i:i+batch_size]
        tasks = []
        
        for user_id, user_tier in batch:
            tasks.append(send_message(
                bot,
                f"🔔 Your {user_tier.capitalize()} tier will expire today. "
                f"You have a 3-day grace period before being automatically *downgraded* to Apprentice tier.",
                chat_id=user_id
            ))
            
        if tasks:
            # Execute batch of expiry notifications concurrently
            await asyncio.gather(*tasks)
            logger.info(f"Sent expiry day notifications to batch of {len(tasks)} users")
    
    # Process downgrades in batches
    logger.info(f"Processing {len(downgrade_users)} users for tier downgrades")
    for i in range(0, len(downgrade_users), batch_size):
        batch_user_ids_str = downgrade_users[i:i+batch_size]
        downgrade_tasks = []
        
        for user_id_str in batch_user_ids_str:
            user_id = int(user_id_str)
            # Step 1: Set tier to apprentice
            await user_collection.update_user_fields(user_id_str, {"tier": "apprentice", "expiry": None})

            # Step 2: Enforce tier-based limit
            downgrade_tasks.append(enforce_token_limit(user_id, bot=bot))
            
        if downgrade_tasks:
            # Execute batch of downgrades concurrently
            await asyncio.gather(*downgrade_tasks)
            
            logger.info(f"Downgraded batch of {len(downgrade_tasks)} users to apprentice tier")
    
    
    logger.info(f"Completed tier expiry processing: {len(reminder_users)} reminders, " 
               f"{len(expiry_today_users)} notifications, {len(downgrade_users)} downgrades")

async def check_and_process_tier_expiry_scheduler(app):
    """
    Scheduled task to run every 2 days to check user tier expiry
    and send reminders or downgrade users as needed
    """
    bot = app.bot
    while True:
        try:
            logger.info("🕒 Running scheduled tier expiry check")
            await check_and_process_tier_expiry(bot)
            # Sleep for 2 days (in seconds)
            await asyncio.sleep(TIER_EXPIRY_CHECK_INTERVAL)
        except asyncio.CancelledError:
            logger.info("❌ Tier expiry check scheduler cancelled")
            break
        except Exception as e:
            logger.error(f"Error in tier expiry check scheduler: {str(e)}")
            # Still sleep before retry, but shorter time
            await asyncio.sleep(TIER_EXPIRY_ERROR_SLEEP)  