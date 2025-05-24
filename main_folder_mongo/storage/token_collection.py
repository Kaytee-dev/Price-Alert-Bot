# token_collection.py
# MongoDB-backed token data manager with in-memory cache support

from mongo_client import get_collection
from pymongo import UpdateOne
from typing import Dict, List
import logging

# In-memory cache
TOKEN_COLLECTION = {}

logger = logging.getLogger(__name__)


def get_tokens_collection():
    return get_collection("tokens")

# --- Load All Tokens ---
async def load_token_collection_from_mongo():
    global TOKEN_COLLECTION
    collection = get_tokens_collection()
    cursor = collection.find()
    TOKEN_COLLECTION = {doc["_id"]: doc async for doc in cursor}

# --- Fetch Tracked Tokens ---
def get_tracked_tokens():
    """
    Retrieve the tracked tokens list from the in-memory cache or the database.
    """
    return TOKEN_COLLECTION.get("tracked_token", {}).get("token_list", {})

# --- Save Tracked Tokens ---
async def save_tracked_tokens(updated_token_list: Dict[str, List[Dict]]):
    """
    Save tracked tokens to MongoDB using $addToSet for appending without overwriting.
    
    :param updated_token_list: Dictionary of chain IDs and their respective tokens.
    """
    collection = get_tokens_collection()

    # Prepare bulk operations for appending tokens
    bulk_operations = []
    for chain_id, tokens in updated_token_list.items():
        bulk_operations.append(
            UpdateOne(
                {"_id": "tracked_token"},
                {"$addToSet": {f"token_list.{chain_id}": {"$each": tokens}}},
                upsert=True
            )
        )

    # Execute bulk operations
    if bulk_operations:
        await collection.bulk_write(bulk_operations)

    # Update in-memory cache
    global TOKEN_COLLECTION
    TOKEN_COLLECTION["tracked_token"] = {"_id": "tracked_token", "token_list": updated_token_list}

# --- Fetch Active Token Data ---
def get_active_token_data():
    """
    Retrieve the active token data from the in-memory cache or the database.
    """
    return TOKEN_COLLECTION.get("active_tokens", {}).get("data", {})

# --- Save Active Token Data ---
async def save_active_token_data(active_data):
    """
    Persist the active token data to the database and update the cache.
    """
    global TOKEN_COLLECTION
    collection = get_tokens_collection()
    await collection.update_one(
        {"_id": "active_tokens"},
        {"$set": {"data": active_data}},
        upsert=True
    )
    TOKEN_COLLECTION["active_tokens"] = {"_id": "active_tokens", "data": active_data}

# --- Bulk Update Tokens ---
async def bulk_update_token_data(updates: list):
    """
    Perform bulk updates on token data in MongoDB and update the in-memory cache.
    """
    collection = get_tokens_collection()

    # Prepare bulk operations
    bulk_operations = []
    for entry in updates:
        if isinstance(entry, dict):
            bulk_operations.append(
                UpdateOne({"_id": entry["_id"]}, {"$set": entry}, upsert=True)
            )
        elif isinstance(entry, UpdateOne):
            bulk_operations.append(entry)
        else:
            raise ValueError(f"Invalid update format: {entry}")

    # Execute bulk write
    if bulk_operations:
        await collection.bulk_write(bulk_operations)

    # Update in-memory cache
    for entry in updates:
        if isinstance(entry, dict):
            TOKEN_COLLECTION[entry["_id"]] = entry

# async def remove_from_tracked_tokens(removals: list[dict]):
#     """
#     Remove tokens from the tracked token list in the database and update the cache.

#     :param removals: List of dictionaries in the format:
#         [
#             {"bsc": ["token_address1", "token_address2"]},
#             {"ethereum": ["token_address3"]}
#         ]
#     """
#     global TOKEN_COLLECTION

#     collection = get_tokens_collection()

#     # Build MongoDB update operations
#     update_operations = {}
#     for chain_update in removals:
#         for chain_id, addresses in chain_update.items():
#             if chain_id not in update_operations:
#                 update_operations[chain_id] = {"$each": addresses}

#     # Execute database update with $pull
#     if update_operations:
#         await collection.update_one(
#             {"_id": "tracked_token"},
#             {
#                 "$pull": {
#                     f"token_list.{chain_id}": {"address": {"$in": addresses}}
#                     for chain_id, addresses in update_operations.items()
#                 }
#             },
#             upsert=True
#         )

#     # Update TOKEN_COLLECTION in-memory cache
#     tracked_doc = TOKEN_COLLECTION.get("tracked_token", {"token_list": {}})
#     token_list = tracked_doc.get("token_list", {})

#     for chain_update in removals:
#         for chain_id, addresses in chain_update.items():
#             if chain_id in token_list:
#                 # Filter out tokens by address
#                 token_list[chain_id] = [
#                     token for token in token_list[chain_id]
#                     if token["address"] not in addresses
#                 ]

#     TOKEN_COLLECTION["tracked_token"] = {"_id": "tracked_token", "token_list": token_list}

async def remove_from_tracked_tokens(removals: list[dict]):
    """
    Remove tokens from the tracked token list in the database and update the cache.

    :param removals: List of dictionaries in the format:
        [
            {"bsc": ["token_address1", "token_address2"]},
            {"ethereum": ["token_address3"]}
        ]
    """
    global TOKEN_COLLECTION

    collection = get_tokens_collection()

    # Build MongoDB update operations for "tracked_token"
    pull_operations = {}
    addresses_to_remove = []

    for chain_update in removals:
        for chain_id, addresses in chain_update.items():
            # Collect addresses for database deletion
            addresses_to_remove.extend(addresses)

            # Prepare $pull operation for "tracked_token"
            pull_operations[f"token_list.{chain_id}"] = {"address": {"$in": addresses}}

            # Update TOKEN_COLLECTION["tracked_token"]["token_list"]
            if "tracked_token" in TOKEN_COLLECTION:
                token_list = TOKEN_COLLECTION["tracked_token"].get("token_list", {})
                if chain_id in token_list:
                    TOKEN_COLLECTION["tracked_token"]["token_list"][chain_id] = [
                        token for token in token_list[chain_id] if token["address"] not in addresses
                    ]

    # Execute $pull for "tracked_token"
    if pull_operations:
        await collection.update_one(
            {"_id": "tracked_token"},
            {"$pull": pull_operations}
        )

    # Remove the documents corresponding to the addresses from TOKEN_COLLECTION
    for address in addresses_to_remove:
        TOKEN_COLLECTION.pop(address, None)

    # Remove documents for token addresses globally
    if addresses_to_remove:
        await collection.delete_many({"_id": {"$in": addresses_to_remove}})

    logger.info(f"✅ Removed tokens globally from tracked_token and {len(addresses_to_remove)} documents.")


async def create_token_list_index():
    """
    Create necessary indexes on the tokens collection for efficient queries.
    """
    collection = get_tokens_collection()

    # Ensure an index on token_list.<chain_id>.address for all possible chain IDs
    index_fields = [
        ("token_list.bsc.address", 1),
        ("token_list.ethereum.address", 1),
        ("token_list.solana.address", 1),
        ("token_list.sui.address", 1)
    ]
    for field, direction in index_fields:
        await collection.create_index([(field, direction)], background=True)

    logger.info("✅ Indexes created on tokens collection for efficient queries.")
