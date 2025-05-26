import storage.user_collection as user_collection

async def remove_user_expiry(user_id: int):
    user_id_str = str(user_id)
    user_doc = user_collection.USER_COLLECTION.get(user_id_str)
    if user_doc and "expiry" in user_doc:
        user_doc.pop("expiry")
        await user_collection.update_user_fields(user_id_str, {"expiry": None})

async def bulk_remove_expiries(user_ids: list[int]):
    updates = []
    for user_id in user_ids:
        user_id_str = str(user_id)
        user_doc = user_collection.USER_COLLECTION.get(user_id_str)
        if user_doc and "expiry" in user_doc:
            user_doc.pop("expiry")
            updates.append({
                "_id": user_id_str,
                "fields": {"expiry": None}
            })

    if updates:
        await user_collection.update_many_user_fields(updates)