# restart_recovery.py
# Mongo-backed logic for restoring active users after a bot restart

import storage.user_collection as user_collection
import storage.users as users
import logging
from pymongo import UpdateOne

logger = logging.getLogger(__name__)

# --- Save active users before shutdown ---
async def mark_active_users_for_restart():
    collection = user_collection.get_user_collection()
    active_users = [uid for uid, active in users.USER_STATUS.items() if active]

    updates = []
    for uid in users.USER_STATUS:
        users.USER_STATUS[uid] = False
        user_collection.USER_COLLECTION.setdefault(uid, {})["status"] = False

    # Prepare bulk operations for MongoDB
    for uid in active_users:
        updates.append(
            UpdateOne(
                {"_id": uid},
                {"$set": {"active_restart": True, "status": False}},
                upsert=True
            )
        )
    if updates:
        await user_collection.bulk_update_user_fields(updates)

    logger.info(f"💾 Marked {len(active_users)} users for active restart recovery and reset statuses.")
# --- Restore active users after restart ---
async def restore_active_users():
    collection = user_collection.get_user_collection()
    restored = 0

    cursor = collection.find({"active_restart": True})
    async for doc in cursor:
        uid = doc["_id"]
        users.USER_STATUS[uid] = True
        user_collection.USER_COLLECTION.setdefault(uid, {})["status"] = True
        user_collection.USER_COLLECTION[uid]["active_restart"] = False
        await user_collection.update_user_fields(uid, {"status": True, "active_restart": False})
        restored += 1

    logger.info(f"♻️ Restored monitoring for {restored} users after restart.")
