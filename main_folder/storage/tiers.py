# storage/tiers.py

import logging
from config import TIERS_FILE, SUPER_ADMIN_ID
from utils import load_json, save_json

import storage.users as users


FREE_LIMIT = 3
STANDARD_LIMIT = 10
PREMIUM_LIMIT = 5
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
    if user_id not in USER_TIERS:
        USER_TIERS[user_id] = "free"
        save_user_tiers()
    return USER_TIERS[user_id]

def get_user_limit(user_id: int) -> int:
    if user_id == SUPER_ADMIN_ID:
        return SUPER_ADMIN_LIMIT
    # elif user_id in ADMINS:
    #     return TIER_LIMITS["premium"]
    
    tier = get_user_tier(user_id)
    return TIER_LIMITS.get(tier, FREE_LIMIT)

def set_user_tier(user_id: int, tier: str):
    if tier not in TIER_LIMITS:
        raise ValueError("Invalid tier name")
    USER_TIERS[str(user_id)] = tier
    save_user_tiers()
    logging.info(f"🎯 Updated user {user_id} to tier '{tier}'")

def is_within_limit(user_id: int, token_count: int) -> bool:
    return token_count <= get_user_limit(user_id)

def delete_user_tier(user_id: int):
    user_id_str = str(user_id)
    if user_id_str in USER_TIERS:
        del USER_TIERS[user_id_str]
        save_user_tiers()

# Promote user to premium tier
def promote_to_premium(user_id: int):
    delete_user_tier(user_id)
    USER_TIERS[str(user_id)] = "premium"
    save_user_tiers()
    enforce_token_limit(user_id)

# def enforce_token_limit(user_id: int):
#     user_id_str = str(user_id)
#     tier_limit = get_user_limit(user_id)
#     tracked = users.USER_TRACKING.get(user_id_str, [])

#     if len(tracked) > tier_limit:
#         users.USER_TRACKING[user_id_str] = tracked[:tier_limit]
#         users.save_user_tracking()
#         logging.info(f"⚠️ User {user_id_str} tracking trimmed to {tier_limit} tokens.")


def enforce_token_limit(user_id: int):
    user_id_str = str(user_id)

    # Step 1: Super Admin Check
    if user_id == SUPER_ADMIN_ID:
        USER_TIERS[user_id_str] = "super_admin"
        save_user_tiers()

    # Step 2: Get tier directly from loaded USER_TIERS
    tier = USER_TIERS.get(user_id_str, "free")

    # Step 3: Get the token limit for that tier
    allowed_limit = TIER_LIMITS.get(tier, FREE_LIMIT)

    # Step 4: Get currently tracked tokens
    current_tokens = users.USER_TRACKING.get(user_id_str, [])

    # Step 5: Enforce limit
    if len(current_tokens) > allowed_limit:
        users.USER_TRACKING[user_id_str] = current_tokens[:allowed_limit]
        users.save_user_tracking()
        logging.info(f"🚫 Enforced token limit for user {user_id_str}. Trimmed to {allowed_limit} tokens.")
