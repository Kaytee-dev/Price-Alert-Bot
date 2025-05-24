# wallets.py
import logging
import random
from typing import Optional, Dict
import storage.payment_collection as payment_collection

# In-memory wallet cache
WALLET_LIST = []

logger = logging.getLogger(__name__)


async def load_wallets():
    """
    Load wallet data from the payments collection into memory.
    """
    global WALLET_LIST
    WALLET_LIST = payment_collection.get_deposit_wallets()
    await initialize_wallet_statuses()

    logger.info("✅ DEPOSIT WALLETS loaded and formatted from database")

async def save_wallets():
    """
    Persist the current wallet list to the database.
    """
    collection = payment_collection.get_payments_collection()

    try:
        # Replace the entire `wallet_list` in the database with the in-memory cache
        await collection.update_one(
            {"_id": "deposit_wallets"},
            {"$set": {"wallets": WALLET_LIST}},
            upsert=True
        )
        payment_collection.PAYMENT_COLLECTION["wallets"] = {"_id": "wallets", "wallet_list": WALLET_LIST}
        logger.info(f"✅ Successfully saved {len(WALLET_LIST)} wallets to the database.")
    except Exception as e:
        logger.error(f"❌ Failed to save wallets to the database: {e}")


async def get_random_wallet() -> Optional[str]:
    if not WALLET_LIST:
        await load_wallets()
    available_wallets = [w for w in WALLET_LIST if w.get("status") == "available"]
    return random.choice(available_wallets)["address"] if available_wallets else None


def get_wallet_by_address(address: str) -> Optional[Dict]:
    for wallet in WALLET_LIST:
        if wallet.get("address") == address:
            return wallet
    return None


async def set_wallet_status(address: str, status: str) -> bool:
    """
    Update wallet status in memory and persist that specific wallet to DB.
    """
    for wallet in WALLET_LIST:
        if wallet.get("address") == address:
            wallet["status"] = status
            return await _persist_wallet_status_to_db(address, status)
    return False

async def mark_wallet_as_available(address: str) -> bool:
    return await set_wallet_status(address, "available")


async def revert_wallet_status_from_context(context) -> bool:
    wallet = context.user_data.get("payment_wallet")
    if wallet:
        return await set_wallet_status(wallet, "available")
    return False


async def initialize_wallet_statuses():
    """
    Ensure all wallets have valid dict structure with 'status'. Persist only updated ones.
    """
    changed_wallets = []

    for i, wallet in enumerate(WALLET_LIST):
        if isinstance(wallet, str):
            WALLET_LIST[i] = {"address": wallet, "status": "available"}
            changed_wallets.append(WALLET_LIST[i])
        elif "status" not in wallet:
            wallet["status"] = "available"
            changed_wallets.append(wallet)

    for wallet in changed_wallets:
        await _persist_wallet_status_to_db(wallet["address"], wallet["status"])


async def _persist_wallet_status_to_db(address: str, status: str) -> bool:
    """
    Update only the status of a specific wallet inside the 'wallets' array in MongoDB.
    """
    collection = payment_collection.get_payments_collection()
    result = await collection.update_one(
        {
            "_id": "deposit_wallets",
            "wallets.address": address
        },
        {
            "$set": {
                "wallets.$.status": status
            }
        }
    )
    # Sync to in-memory cache
    if "deposit_wallets" in payment_collection.PAYMENT_COLLECTION:
        for w in payment_collection.PAYMENT_COLLECTION["deposit_wallets"].get("wallets", []):
            if w["address"] == address:
                w["status"] = status
                break
    return result.modified_count > 0