# payout.py
import logging
import random
from typing import List, Optional
import storage.payment_collection as payment_collection

PAYOUT_WALLETS: List[str] = []

logger = logging.getLogger(__name__)

def load_payout_wallets():
    """
    Load payout wallet list from the payments collection into memory.
    """
    global PAYOUT_WALLETS
    PAYOUT_WALLETS = payment_collection.get_withdrawal_wallets()
    logger.info("✅ PAYOUT WALLETS loaded and formatted from database")


def get_next_payout_wallet() -> Optional[str]:
    if not PAYOUT_WALLETS:
        load_payout_wallets()
    return random.choice(PAYOUT_WALLETS) if PAYOUT_WALLETS else None


def get_payout_wallets() -> List[str]:
    if not PAYOUT_WALLETS:
        load_payout_wallets()
    return PAYOUT_WALLETS


async def add_wallet_to_payout_list(address: str) -> bool:
    """
    Add a payout address to the MongoDB and in-memory list if not present.
    """
    if address not in PAYOUT_WALLETS:
        PAYOUT_WALLETS.append(address)

        # Persist single address using $addToSet
        collection = payment_collection.get_payments_collection()
        await collection.update_one(
            {"_id": "withdrawal_wallets"},
            {"$addToSet": {"wallets": address}},
            upsert=True
        )

        # Sync cache
        if "withdrawal_wallets" in payment_collection.PAYMENT_COLLECTION:
            payment_collection.PAYMENT_COLLECTION["withdrawal_wallets"]["wallets"] = PAYOUT_WALLETS

        return True
    return False

async def add_wallets_to_payout_bulk(addresses: List[str]) -> List[str]:
    """
    Add multiple payout addresses at once. Only unique addresses are added.
    Returns list of newly added addresses.
    """
    new = [addr for addr in addresses if addr not in PAYOUT_WALLETS]
    if not new:
        return []

    PAYOUT_WALLETS.extend(new)

    # Persist with one atomic $addToSet $each
    collection = payment_collection.get_payments_collection()
    await collection.update_one(
        {"_id": "withdrawal_wallets"},
        {"$addToSet": {"wallets": {"$each": new}}},
        upsert=True
    )

    # Sync Mongo cache
    if "withdrawal_wallets" in payment_collection.PAYMENT_COLLECTION:
        payment_collection.PAYMENT_COLLECTION["withdrawal_wallets"]["wallets"] = PAYOUT_WALLETS

    return new

async def remove_wallets_from_payout(addresses: List[str]) -> List[str]:
    """
    Remove payout wallet addresses from MongoDB and memory.
    Returns list of successfully removed addresses.
    """
    global PAYOUT_WALLETS

    to_remove = [a for a in addresses if a in PAYOUT_WALLETS]
    if not to_remove:
        return []

    # Update in-memory
    PAYOUT_WALLETS = [addr for addr in PAYOUT_WALLETS if addr not in to_remove]

    # Update MongoDB
    collection = payment_collection.get_payments_collection()
    await collection.update_one(
        {"_id": "withdrawal_wallets"},
        {"$pull": {"wallets": {"$in": to_remove}}}
    )

    # Sync Mongo cache
    if "withdrawal_wallets" in payment_collection.PAYMENT_COLLECTION:
        payment_collection.PAYMENT_COLLECTION["withdrawal_wallets"]["wallets"] = PAYOUT_WALLETS

    return to_remove
