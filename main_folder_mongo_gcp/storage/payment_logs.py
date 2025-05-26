import logging
from datetime import datetime
from typing import Optional, Tuple
import storage.payment_collection as payment_collection

PAYMENT_LOGS = {}  # In-memory: {user_id: {payment_id: data}}

logger = logging.getLogger(__name__)

async def load_payment_logs():
    """
    Load payment logs from `payment_collection.py` and populate the in-memory cache.
    """
    global PAYMENT_LOGS
    # Use payment_collection as the source of truth
    PAYMENT_LOGS = {
        user_id: payment_collection.get_user_payment_log(user_id)
        for user_id in payment_collection.PAYMENT_COLLECTION
        if "payments" in payment_collection.PAYMENT_COLLECTION[user_id]
    }

    logger.info("✅ PAYMENT LOGS loaded and formatted from database")


async def save_payment_logs():
    """
    Save the in-memory cache to MongoDB using bulk operations.
    """
    global PAYMENT_LOGS

    # Prepare bulk update operations
    updates = [
        {
            "_id": user_id,
            "payments": payments
        }
        for user_id, payments in PAYMENT_LOGS.items()
    ]

    # Use payment_collection's bulk update functionality
    await payment_collection.bulk_update_payment_data(updates)


async def log_user_payment(user_id: int, payment_id: str, data: dict) -> None:
    """
    Store a user's payment attempt under their ID and payment_id.
    """
    global PAYMENT_LOGS
    user_key = str(user_id)

    # Ensure user_key exists in PAYMENT_LOGS
    if user_key not in PAYMENT_LOGS:
        PAYMENT_LOGS[user_key] = {}

    # Log the payment
    PAYMENT_LOGS[user_key][payment_id] = {
        **data,
        "logged_at": datetime.now().isoformat()
    }

    # Persist the payment log
    await payment_collection.save_user_payment_log(user_key, PAYMENT_LOGS[user_key])


async def get_user_payment(user_id: int, payment_id: str) -> Optional[dict]:
    """
    Get a specific user's payment details.
    """
    user_key = str(user_id)

    # First, check the in-memory cache
    if user_key in PAYMENT_LOGS:
        return PAYMENT_LOGS[user_key].get(payment_id)

    # Fallback to payment_collection for database fetch
    return payment_collection.get_user_payment_log(user_key).get(payment_id)


async def find_payment_globally(payment_id: str) -> Optional[Tuple[str, dict]]:
    """
    Search for a payment ID globally across all users.
    """
    global PAYMENT_LOGS

    # Search in the in-memory cache first
    for user_id, payments in PAYMENT_LOGS.items():
        if payment_id in payments:
            return user_id, payments[payment_id]

    # Search in the database using `payment_collection.PAYMENT_COLLECTION`
    for user_id, user_data in payment_collection.PAYMENT_COLLECTION.items():
        payments = user_data.get("payments", {})
        if payment_id in payments:
            return user_id, payments[payment_id]

    return None


async def remove_user_payment(user_id: int, payment_id: str) -> None:
    """
    Remove a specific payment entry for a user.
    """
    user_key = str(user_id)

    # Remove from in-memory cache
    if user_key in PAYMENT_LOGS:
        PAYMENT_LOGS[user_key].pop(payment_id, None)

    # Remove from the database
    await payment_collection.remove_fields_from_payment_document(user_key, [payment_id])
