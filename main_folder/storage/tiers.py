# storage/tiers.py

import logging
from config import TIERS_FILE, SUPER_ADMIN_ID
from utils import load_json, save_json, send_message
from typing import Optional
from telegram import Bot

import storage.users as users


FREE_LIMIT = 3
STANDARD_LIMIT = 10
PREMIUM_LIMIT = 20
SUPER_ADMIN_LIMIT = 999

TIER_LIMITS = {
    "free": FREE_LIMIT,
    "standard": STANDARD_LIMIT,
    "premium": PREMIUM_LIMIT,
    "super_admin": SUPER_ADMIN_LIMIT,
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
        USER_TIERS[user_id_str] = "free"
        save_user_tiers()
    return USER_TIERS[user_id_str]


def get_user_limit(user_id: int) -> int:
    if user_id == SUPER_ADMIN_ID:
        return SUPER_ADMIN_LIMIT
    # elif user_id in ADMINS:
    #     return TIER_LIMITS["premium"]
    
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
    await set_user_tier(user_id, "premium", bot=bot)


def enforce_token_limit_core(user_id: int) -> bool:
    user_id_str = str(user_id)

    if user_id == SUPER_ADMIN_ID:
        USER_TIERS[user_id_str] = "super_admin"
        save_user_tiers()

    tier = USER_TIERS.get(user_id_str, "free")
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
        tier = USER_TIERS.get(str(user_id), "free")
        allowed_limit = TIER_LIMITS.get(tier, FREE_LIMIT)
        await send_message(
            bot,
            f"🚫 Your tracked tokens exceeded your tier limit ({tier}). We trimmed it to the first {allowed_limit} token(s).",
            chat_id=user_id
        )
