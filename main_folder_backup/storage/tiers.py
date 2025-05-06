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
    logging.info(f"🎯 Updated user {user_id} to tier '{tier}'")
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
        logging.info(f"🚫 Enforced token limit for user {user_id_str}. Trimmed to {allowed_limit} tokens.")
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

async def check_and_process_tier_expiry(bot: Bot):
    """
    Check for users with expiring tiers and process accordingly:
    - Send reminder 3 days before expiry
    - Send notice on expiry day
    - Downgrade after 3-day grace period
    """
    current_date = datetime.now()
    
    # Ensure expiry data is loaded
    expiry.load_user_expiry()
    
    for user_id_str, expiry_str in expiry.USER_EXPIRY.items():
        try:
            user_id = int(user_id_str)
            expiry_date = datetime.fromisoformat(expiry_str)
            
            # Calculate days until expiry
            days_until_expiry = (expiry_date - current_date).days
            
            # Check if tier is not free already
            user_tier = get_user_tier(user_id)
            if user_tier == "apprentice":
                continue
                
            # Send reminder 3 days before expiry
            if days_until_expiry <= 3:
                await send_message(
                    bot,
                    f"⚠️ Your {user_tier.capitalize()} tier will expire in {days_until_expiry} days. " 
                    f"Please renew your tier using /renew to keep your current benefits.",
                    chat_id=user_id
                )
                logging.info(f"Sent {days_until_expiry}-day expiry reminder to user {user_id}")
                
            # Send notice on expiry day
            elif days_until_expiry == 0:
                await send_message(
                    bot,
                    f"🔔 Your {user_tier.capitalize()} tier has expired today. "
                    f"You have a 3-day grace period before being automatically *downgraded* to Apprentice tier.",
                    chat_id=user_id
                )
                logging.info(f"Sent expiry notice to user {user_id}")
                
            # Process downgrade after grace period (3 days)
            elif days_until_expiry < -3:
                # Downgrade to free tier
                await set_user_tier(user_id, "apprentice", bot=bot)
                
                # Clean up expiry record
                del expiry.USER_EXPIRY[user_id_str]
                expiry.save_user_expiry()
                
                logging.info(f"Downgraded user {user_id} to apprentice tier after grace period")
                
        except (ValueError, TypeError) as e:
            logging.error(f"Error processing expiry for user {user_id_str}: {str(e)}")


async def check_and_process_tier_expiry_scheduler(app):
    """
    Scheduled task to run every 2 days to check user tier expiry
    and send reminders or downgrade users as needed
    """
    bot = app.bot
    while True:
        try:
            logging.info("🕒 Running scheduled tier expiry check")
            await check_and_process_tier_expiry(bot)
            # Sleep for 2 days (in seconds)
            await asyncio.sleep(2 * 24 * 60 * 60)  # 2 days
        except asyncio.CancelledError:
            logging.info("❌ Tier expiry check scheduler cancelled")
            break
        except Exception as e:
            logging.error(f"Error in tier expiry check scheduler: {str(e)}")
            # Still sleep before retry, but shorter time
            await asyncio.sleep(1 * 60 * 60)  # 1 hour