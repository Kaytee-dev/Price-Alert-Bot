# user_tracking.py
# Mongo-backed user tracking logic with in-memory cache

import logging
import storage.user_collection as user_collection

USER_TRACKING = {}  # user_id -> { chain_id: [addr, ...] }
USER_STATUS = {}    # user_id -> bool

logger = logging.getLogger(__name__)

# --- Load from central Mongo-backed cache ---
def load_user_tracking():
    global USER_TRACKING
    USER_TRACKING = {uid: doc.get("tracking", {}) for uid, doc in user_collection.USER_COLLECTION.items()}
    logger.info("✅ USER_TRACKING loaded from user_collection")

def load_user_status():
    global USER_STATUS
    USER_STATUS = {uid: doc.get("status", False) for uid, doc in user_collection.USER_COLLECTION.items()}
    logger.info("✅ USER_STATUS loaded from user_collection")

# --- Save user tracking back to Mongo ---
def save_user_tracking():
    for uid, tracking in USER_TRACKING.items():
        user_collection.USER_COLLECTION.setdefault(uid, {})["tracking"] = tracking

# --- Save user status back to Mongo ---
async def save_user_status(user_id: str):
    status = USER_STATUS.get(user_id, False)
    await user_collection.update_user_fields(user_id, {"status": status})

# --- Save one token addition ---
async def save_user_tracking_to_mongo_single_token(user_id: str, chain_id: str, token: tuple[str, str]):
    address, _ = token  # we only store the address
    collection = user_collection.get_user_collection()

    await collection.update_one(
        {"_id": user_id},
        {"$addToSet": {f"tracking.{chain_id}": address}},
        upsert=True
    )

    user_doc = user_collection.USER_COLLECTION.setdefault(user_id, {}).setdefault("tracking", {})
    if address not in user_doc.setdefault(chain_id, []):
        user_doc[chain_id].append(address)


# --- Save multiple tokens per-chain ---
async def save_user_tracking_batch(user_id: str, added: dict[str, list[tuple[str, str]]]):
    # Flatten to only address per chain
    push_ops = {
        f"tracking.{chain}": {"$each": [addr for addr, _ in tokens]}
        for chain, tokens in added.items()
    }

    collection = user_collection.get_user_collection()
    await collection.update_one(
        {"_id": user_id},
        {"$push": push_ops},
        upsert=True
    )

    user_doc = user_collection.USER_COLLECTION.setdefault(user_id, {}).setdefault("tracking", {})
    for chain, tokens in added.items():
        addresses = [addr for addr, _ in tokens]
        user_doc.setdefault(chain, []).extend([
            addr for addr in addresses if addr not in user_doc[chain]
        ])

# --- Remove one token from tracking ---
async def remove_token_from_user(user_id: str, chain_id: str, token_address: str):
    collection = user_collection.get_user_collection()
    await collection.update_one(
        {"_id": user_id},
        {"$pull": {f"tracking.{chain_id}": token_address}}
    )
    try:
        user_doc = user_collection.USER_COLLECTION[user_id]["tracking"]
        if chain_id in user_doc and token_address in user_doc[chain_id]:
            user_doc[chain_id].remove(token_address)
            if not user_doc[chain_id]:
                del user_doc[chain_id]
    except KeyError:
        pass


# --- Remove many tokens grouped by chain ---
async def remove_tokens_batch(user_id: str, removed: dict[str, list[str]]):
    collection = user_collection.get_user_collection()

    # Build $pull with $in
    pull_ops = {
        f"tracking.{chain}": {"$in": tokens}
        for chain, tokens in removed.items()
    }
    await collection.update_one({"_id": user_id}, {"$pull": pull_ops})

    user_doc = user_collection.USER_COLLECTION.get(user_id, {}).get("tracking", {})
    for chain, tokens in removed.items():
        if chain in user_doc:
            user_doc[chain] = [t for t in user_doc[chain] if t not in tokens]
            if not user_doc[chain]:
                del user_doc[chain]


# --- Clear full user tracking (used in /reset) ---
async def clear_user_tracking(user_id: str):
    collection = user_collection.get_user_collection()
    await collection.update_one(
        {"_id": user_id},
        {"$unset": {"tracking": ""}}
    )
    user_collection.USER_COLLECTION.get(user_id, {}).pop("tracking", None)

async def overwrite_user_tracking(user_id: str, new_tracking: dict[str, list[str]]):
    collection = user_collection.get_user_collection()
    await collection.update_one(
        {"_id": user_id},
        {"$set": {"tracking": new_tracking}},
        upsert=True
    )
    user_collection.USER_COLLECTION.setdefault(user_id, {})["tracking"] = new_tracking
