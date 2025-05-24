# payment_collection.py
# MongoDB-backed payment data manager with in-memory cache support

from mongo_client import get_collection
from pymongo import UpdateOne
from typing import Dict, List, Any
import logging

# In-memory cache
PAYMENT_COLLECTION = {}

logger = logging.getLogger(__name__)

def get_payments_collection():
    return get_collection("payments")

# --- Load All Payments ---
async def load_payment_collection_from_mongo():
    global PAYMENT_COLLECTION
    collection = get_payments_collection()
    cursor = collection.find()
    PAYMENT_COLLECTION = {doc["_id"]: doc async for doc in cursor}

# --- Get Deposit Wallets ---
def get_deposit_wallets() -> List[Dict[str, str]]:
    return PAYMENT_COLLECTION.get("deposit_wallets", {}).get("wallets", [])

# --- Get Wallet Secrets ---
def get_wallet_secrets() -> Dict[str, str]:
    return PAYMENT_COLLECTION.get("wallet_secrets", {}).get("secrets", {})

# --- Get Withdrawal Wallets ---
def get_withdrawal_wallets() -> List[str]:
    return PAYMENT_COLLECTION.get("withdrawal_wallets", {}).get("wallets", [])

# --- Get User Payment Logs ---
def get_user_payment_log(user_id: str) -> Dict[str, Any]:
    return PAYMENT_COLLECTION.get(user_id, {}).get("payments", {})

# --- Save User Payment Log ---
async def save_user_payment_log(user_id: str, payments: Dict[str, Any]):
    collection = get_payments_collection()
    doc = {"_id": user_id, "payments": payments}
    await collection.update_one({"_id": user_id}, {"$set": doc}, upsert=True)
    PAYMENT_COLLECTION[user_id] = doc

# --- Bulk Update Payments ---
async def bulk_update_payment_data(updates: List[dict | UpdateOne]):
    collection = get_payments_collection()

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

    if bulk_operations:
        await collection.bulk_write(bulk_operations)

    for entry in updates:
        if isinstance(entry, dict):
            PAYMENT_COLLECTION[entry["_id"]] = entry

# --- Remove Entries from Document by ID ---
async def remove_fields_from_payment_document(doc_id: str, keys_to_remove: List[str]):
    """
    Removes specified keys from the 'payments' field of a user document.
    """
    global PAYMENT_COLLECTION
    collection = get_payments_collection()

    pull_ops = {f"payments.{key}": "" for key in keys_to_remove}
    unset_query = {"$unset": pull_ops}

    await collection.update_one({"_id": doc_id}, unset_query)

    # Update in-memory cache
    if doc_id in PAYMENT_COLLECTION:
        payments = PAYMENT_COLLECTION[doc_id].get("payments", {})
        for key in keys_to_remove:
            payments.pop(key, None)
        PAYMENT_COLLECTION[doc_id]["payments"] = payments

    logger.info(f"✅ Removed {len(keys_to_remove)} entries from '{doc_id}' payments.")
