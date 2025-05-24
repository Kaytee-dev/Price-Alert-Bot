from typing import Dict
import storage.user_collection as user_collection

USER_THRESHOLDS: Dict[str, float] = {}

async def load_user_thresholds():
    """
    Load all user thresholds from the database into memory,
    initializing missing thresholds with the default value.
    """
    global USER_THRESHOLDS
    default_threshold = 5.0

    updates = []  # Prepare updates for users missing the threshold key
    for user_id, doc in user_collection.USER_COLLECTION.items():
        # Get or initialize the threshold
        threshold = doc.get("threshold", default_threshold)
        USER_THRESHOLDS[user_id] = threshold

        # If the threshold key is missing, schedule it for database update
        if "threshold" not in doc:
            updates.append({"_id": user_id, "fields": {"threshold": default_threshold}})

    # Update the database for missing thresholds
    if updates:
        await user_collection.bulk_update_user_fields(updates)



async def save_user_thresholds():
    """
    Persist all user thresholds from memory to the database.
    """
    updates = [
        {"_id": user_id, "fields": {"threshold": value}}
        for user_id, value in USER_THRESHOLDS.items()
    ]
    await user_collection.bulk_update_user_fields(updates)

async def update_user_threshold(user_id: str, threshold: float):
    """
    Update a user's threshold in memory and persist it to the database.
    If the user does not have an existing threshold, it initializes it with a default value.
    """
    default_threshold = 5.0

    # Ensure the threshold is initialized in memory
    USER_THRESHOLDS.setdefault(user_id, default_threshold)

    # Update the threshold in memory
    USER_THRESHOLDS[user_id] = threshold

    # Persist to the database
    await user_collection.update_user_fields(user_id, {"threshold": threshold})
