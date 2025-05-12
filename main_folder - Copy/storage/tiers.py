# storage/tiers.py

import logging
import asyncio
from config import TIERS_FILE, SUPER_ADMIN_ID
from util.utils import load_json, save_json, send_message
from typing import Optional
from telegram import Bot

from datetime import datetime

import storage.users as users
import storage.expiry as expiry

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

def load_user_tiers():
    global USER_TIERS
    USER_TIERS = load_json(TIERS_FILE, {}, "user tiers")

def save_user_tiers():
    save_json(TIERS_FILE, USER_TIERS, "user tiers")

def get_user_tier(user_id: int) -> str:
    user_id_str = str(user_id)
    if user_id_str not in USER_TIERS:
        USER_TIERS[user_id_str] = "apprentice"
        save_user_tiers()
    return USER_TIERS[user_id_str]


def get_user_limit(user_id: int) -> int:
    if user_id == SUPER_ADMIN_ID:
        return SUPER_ADMIN_LIMIT

    tier = get_user_tier(user_id)
    return TIER_LIMITS.get(tier, FREE_LIMIT)

def set_user_tier_core(user_id: int, tier: str) -> bool:
    if tier not in TIER_LIMITS:
        raise ValueError("Invalid tier name")
    user_id_str = str(user_id)
    USER_TIERS[user_id_str] = tier
    save_user_tiers()
    logger.info(f"🎯 Updated user {user_id} to tier '{tier}'")
    trimmed = enforce_token_limit_core(user_id)
    return trimmed

async def set_user_tier(user_id: int, tier: str, bot: Optional[Bot] = None):
    trimmed = set_user_tier_core(user_id, tier)

    if bot:
        limit = get_user_limit(user_id)
        send_message_text = f"🎯 Your tier has been updated to *{tier.capitalize()}*. You can now track up to {limit} token(s)."
        if trimmed:
            send_message_text += f"\n🚫 Your tracked tokens were trimmed to match the new tier limit."
        await send_message(
            bot,
            send_message_text,
            chat_id=user_id
        )

def is_within_limit(user_id: int, token_count: int) -> bool:
    return token_count <= get_user_limit(user_id)

def delete_user_tier(user_id: int):
    user_id_str = str(user_id)
    if user_id_str in USER_TIERS:
        del USER_TIERS[user_id_str]
        save_user_tiers()

async def promote_to_premium(user_id: int, bot: Optional[Bot] = None):
    await set_user_tier(user_id, "Chieftain", bot=bot)


def enforce_token_limit_core(user_id: int) -> bool:
    user_id_str = str(user_id)

    if user_id == SUPER_ADMIN_ID:
        USER_TIERS[user_id_str] = "super admin"
        save_user_tiers()

    tier = USER_TIERS.get(user_id_str, "apprentice")
    allowed_limit = TIER_LIMITS.get(tier, FREE_LIMIT)
    current_tokens = users.USER_TRACKING.get(user_id_str, [])

    if len(current_tokens) > allowed_limit:
        users.USER_TRACKING[user_id_str] = current_tokens[:allowed_limit]
        users.save_user_tracking()
        logger.info(f"🚫 Enforced token limit for user {user_id_str}. Trimmed to {allowed_limit} tokens.")
        return True
    return False

async def enforce_token_limit(user_id: int, bot: Optional[Bot] = None):
    trimmed = enforce_token_limit_core(user_id)
    if trimmed and bot:
        tier = USER_TIERS.get(str(user_id), "apprentice")
        allowed_limit = TIER_LIMITS.get(tier, FREE_LIMIT)
        await send_message(
            bot,
            f"🚫 Your tracked tokens exceeded your tier limit ({tier}). We trimmed it to the first {allowed_limit} token(s).",
            chat_id=user_id
        )

def set_user_expiry(user_id: int, expiry_date: datetime):
    user_id_str = str(user_id)
    expiry.USER_EXPIRY[user_id_str] = expiry_date.isoformat()
    expiry.save_user_expiry()


def get_user_expiry(user_id: int) -> datetime | None:
    user_id_str = str(user_id)
    expiry_str = expiry.USER_EXPIRY.get(user_id_str)
    if expiry_str:
        try:
            return datetime.fromisoformat(expiry_str)
        except ValueError:
            return None
    return None

# async def check_and_process_tier_expiry(bot: Bot):
#     """
#     Check for users with expiring tiers and process accordingly:
#     - Send reminder 3 days before expiry
#     - Send notice on expiry day
#     - Downgrade after 3-day grace period.
#     - 
#     """
#     current_date = datetime.now()
    
#     # Ensure expiry data is loaded
#     expiry.load_user_expiry()

#     # Process in batches of 50
#     batch_size = 50
#     user_ids_str = list(expiry.USER_EXPIRY.keys())
    
#     for user_id_str, expiry_str in expiry.USER_EXPIRY.items():
#         try:
#             user_id = int(user_id_str)
#             expiry_date = datetime.fromisoformat(expiry_str)
            
#             # Calculate days until expiry
#             days_until_expiry = (expiry_date - current_date).days
#             grace_period = 3
#             grace_period_remaining = grace_period + days_until_expiry
            
#             # Check if tier is not free already
#             user_tier = get_user_tier(user_id)
#             if user_tier == "apprentice":
#                 continue
                
#             # Send reminder 3 days before expiry
#             if days_until_expiry in range(1,4):
#                 await send_message(
#                     bot,
#                     f"⚠️ Your {user_tier.capitalize()} tier will expire in {days_until_expiry} days. " 
#                     f"Kindly renew your tier using /renew to keep your current benefits.",
#                     chat_id=user_id
#                 )
#                 logger.info(f"Sent {days_until_expiry}-day expiry reminder to user {user_id}")
                
#             # Send notice on expiry day
#             elif days_until_expiry == 0:
#                 await send_message(
#                     bot,
#                     f"🔔 Your {user_tier.capitalize()} tier will expire today. "
#                     f"You have a 3-day grace period before being automatically *downgraded* to Apprentice tier.",
#                     chat_id=user_id
#                 )
#                 logger.info(f"Sent expiry notice to user {user_id}")
                
#             # Process downgrade after grace period (3 days)
#             elif grace_period_remaining <= 0:
#                 # Downgrade to free tier
#                 await set_user_tier(user_id, "apprentice", bot=bot)
                
#                 # Clean up expiry record
#                 del expiry.USER_EXPIRY[user_id_str]
#                 expiry.save_user_expiry()
                
#                 logger.info(f"Downgraded user {user_id} to apprentice tier after grace period")
                
#         except (ValueError, TypeError) as e:
#             logger.error(f"Error processing expiry for user {user_id_str}: {str(e)}")

async def check_and_process_tier_expiry(bot: Bot):
    """
    Check for users with expiring tiers and process accordingly:
    - Send reminder 3 days before expiry
    - Send notice on expiry day
    - Downgrade after 3-day grace period
    
    Uses true batch processing to optimize performance and reduce API load
    """
    current_date = datetime.now()
    
    # Ensure expiry data is loaded
    expiry.load_user_expiry()

    # Batch size for processing
    batch_size = 50
    user_ids_str = list(expiry.USER_EXPIRY.keys())
    total_users = len(user_ids_str)
    
    # Group users by action type to enable proper batching
    reminder_users = []      # 1-3 days before expiry
    expiry_today_users = []  # expiry day
    downgrade_users = []     # past grace period
    
    # First pass: categorize all users
    for i in range(0, total_users, batch_size):
        batch_user_ids = user_ids_str[i:i+batch_size]
        
        for user_id_str in batch_user_ids:
            try:
                user_id = int(user_id_str)
                expiry_date = datetime.fromisoformat(expiry.USER_EXPIRY[user_id_str])
                
                # Calculate days until expiry
                days_until_expiry = (expiry_date - current_date).days
                grace_period = 3
                grace_period_remaining = grace_period + days_until_expiry
                
                # Check if tier is not free already
                user_tier = get_user_tier(user_id)
                if user_tier == "apprentice":
                    continue
                    
                # Categorize based on expiry status
                if days_until_expiry in range(1, 4):
                    reminder_users.append((user_id, user_tier, days_until_expiry))
                elif days_until_expiry == 0:
                    expiry_today_users.append((user_id, user_tier))
                elif grace_period_remaining <= 0:
                    downgrade_users.append(user_id_str)
                    
            except (ValueError, TypeError) as e:
                logger.error(f"Error processing expiry for user {user_id_str}: {str(e)}")
    
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
            downgrade_tasks.append(set_user_tier(user_id, "apprentice", bot=bot))
        
        if downgrade_tasks:
            # Execute batch of downgrades concurrently
            await asyncio.gather(*downgrade_tasks)
            
            # Clean up expiry records for this batch
            for user_id_str in batch_user_ids_str:
                if user_id_str in expiry.USER_EXPIRY:
                    del expiry.USER_EXPIRY[user_id_str]
            
            # Save changes after each batch to prevent data loss
            expiry.save_user_expiry()
            logger.info(f"Downgraded batch of {len(downgrade_tasks)} users to apprentice tier")
    
    # Final save to ensure any remaining changes are persisted
    expiry.save_user_expiry()
    
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