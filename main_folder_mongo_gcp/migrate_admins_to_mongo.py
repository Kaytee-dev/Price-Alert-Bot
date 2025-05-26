# migrate_admins_to_mongo.py

import asyncio
import json
from pathlib import Path
from mongo_client import connect, disconnect, get_collection
from config import ADMINS_FILE, SUPER_ADMIN_ID

async def migrate_admins():
    # Load legacy JSON admin list
    path = Path(ADMINS_FILE)
    if not path.exists():
        print(f"❌ Admin file not found: {ADMINS_FILE}")
        return

    with open(path, "r", encoding="utf-8") as f:
        admins = json.load(f)

    # Normalize to set, enforce super admin presence
    admin_set = set(admins)
    admin_set.add(SUPER_ADMIN_ID)

    # Connect to MongoDB and upsert
    await connect()
    collection = get_collection("admins")

    await collection.update_one(
        {"_id": "admin_list"},
        {"$set": {"user_ids": list(admin_set)}},
        upsert=True
    )
    await disconnect()

    print(f"✅ Migrated {len(admin_set)} admins to MongoDB.")

if __name__ == "__main__":
    asyncio.run(migrate_admins())
