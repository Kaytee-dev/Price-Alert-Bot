import logging
from mongo_client import get_collection
from config import SUPER_ADMIN_ID


ADMINS = set()
logger = logging.getLogger(__name__)

# --- Load/Save Admins ---
async def load_admins():
    """
    Async: Load the list of admin user_ids from MongoDB and ensure all are integers.
    """
    global ADMINS
    collection = get_collection("admins")
    doc = await collection.find_one({"_id": "admin_list"})
    
    if doc and "user_ids" in doc:
        # Cast all user IDs to int safely
        ADMINS = set(int(uid) for uid in doc["user_ids"])
    else:
        ADMINS = set()

    ADMINS.add(int(SUPER_ADMIN_ID))
    logger.info("✅ ADMINS loaded from admins collection")

async def save_admins():
    """
    Async: Save ADMINS to MongoDB and refresh cache.
    """
    global ADMINS
    collection = get_collection("admins")
    await collection.update_one(
        {"_id": "admin_list"},
        {"$set": {"user_ids": list(ADMINS)}},
        upsert=True
    )
    # Refresh cache from what was saved
    ADMINS = set(ADMINS)
    ADMINS.add(SUPER_ADMIN_ID)