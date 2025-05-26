# user_collection.py
# MongoDB-backed user data manager with in-memory cache support

from mongo_client import get_collection
from pymongo import UpdateOne


# In-memory cache
USER_COLLECTION = {}

def get_user_collection():
    return get_collection("users")

# --- Load All Users ---
async def load_user_collection_from_mongo():
    global USER_COLLECTION
    collection = get_user_collection()
    cursor = collection.find()
    USER_COLLECTION = {doc["_id"]: doc async for doc in cursor}

# --- Fetch User ---
def get_user(user_id: str) -> dict:
    return USER_COLLECTION.get(user_id, {})

# --- Partial Update (One) ---
async def update_user_fields(user_id: str, fields: dict):
    collection = get_user_collection()
    await collection.update_one({"_id": user_id}, {"$set": fields}, upsert=True)
    USER_COLLECTION.setdefault(user_id, {}).update(fields)

# --- Partial Update (Many) ---
async def update_many_user_fields(updates: list[dict]):
    for entry in updates:
        user_id = entry["_id"]
        fields = entry["fields"]
        await update_user_fields(user_id, fields)

# --- Replace One User ---
async def replace_user(user_id: str, new_data: dict):
    new_data["_id"] = user_id
    collection = get_user_collection()
    await collection.replace_one({"_id": user_id}, new_data, upsert=True)
    USER_COLLECTION[user_id] = new_data

# --- Replace Many Users ---
async def replace_many_users(replacements: list[dict]):
    for doc in replacements:
        await replace_user(doc["_id"], doc)

# --- Delete One ---
async def delete_user(user_id: str):
    collection = get_user_collection()
    await collection.delete_one({"_id": user_id})
    USER_COLLECTION.pop(user_id, None)

# --- Delete Many ---
async def delete_users(user_ids: list):
    collection = get_user_collection()
    await collection.delete_many({"_id": {"$in": user_ids}})
    for uid in user_ids:
        USER_COLLECTION.pop(uid, None)

# --- Insert New User (optional) ---
async def insert_new_user(user_id: str, initial_data: dict):
    collection = get_user_collection()
    await collection.insert_one({"_id": user_id, **initial_data})
    USER_COLLECTION[user_id] = {"_id": user_id, **initial_data}

# --- Bulk Update Users ---
# async def bulk_update_user_fields(updates: list[dict]):
#     """
#     Perform bulk updates on user fields in MongoDB.

#     :param updates: List of dictionaries with structure:
#         [
#             {"_id": "user_id", "fields": {"field1": value1, "field2": value2}},
#             ...
#         ]
#     """
#     collection = get_user_collection()

#     bulk_operations = [
#         UpdateOne({"_id": entry["_id"]}, {"$set": entry["fields"]}, upsert=True)
#         for entry in updates
#     ]

#     if bulk_operations:
#         await collection.bulk_write(bulk_operations)

#     # Update in-memory cache
#     for entry in updates:
#         user_id = entry["_id"]
#         USER_COLLECTION.setdefault(user_id, {}).update(entry["fields"])

async def bulk_update_user_fields(updates: list):
    """
    Perform bulk updates on user fields in MongoDB.

    :param updates: List of dictionaries or `UpdateOne` objects.
    """
    collection = get_user_collection()

    # Convert dictionaries to `UpdateOne`, if necessary
    bulk_operations = []
    for entry in updates:
        if isinstance(entry, dict):
            bulk_operations.append(
                UpdateOne({"_id": entry["_id"]}, {"$set": entry["fields"]}, upsert=True)
            )
        elif isinstance(entry, UpdateOne):
            bulk_operations.append(entry)
        else:
            raise ValueError(f"Invalid update format: {entry}")

    if bulk_operations:
        await collection.bulk_write(bulk_operations)

    # Update in-memory cache only for dictionaries
    for entry in updates:
        if isinstance(entry, dict):
            user_id = entry["_id"]
            USER_COLLECTION.setdefault(user_id, {}).update(entry["fields"])



# --- Ensure Indexes ---
async def ensure_user_indexes():
    collection = get_user_collection()
    await collection.create_index("tier")
    await collection.create_index("expiry")
    await collection.create_index("referral.wallet_address")
    await collection.create_index("referral.successful_referrals")
    await collection.create_index("active_restart")
