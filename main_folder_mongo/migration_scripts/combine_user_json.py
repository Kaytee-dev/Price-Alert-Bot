import json
from pathlib import Path

# Load JSON files
base_path = Path("storage/data")

def load_json(filename):
    with open(base_path / filename, "r", encoding="utf-8") as f:
        return json.load(f)

user_tracking = load_json("user_tracking.json")
user_status = load_json("user_status.json")
user_threshold = load_json("user_threshold.json")
user_tiers = load_json("user_tiers.json")
user_expiry = load_json("user_expiry.json")
user_referral = load_json("user_referral.json")

# active_restart_users is a list of IDs
with open(base_path / "active_restart_users.json", "r", encoding="utf-8") as f:
    active_restart_set = set(json.load(f))

# Combine
combined = {}
user_ids = set(
    list(user_tracking.keys()) +
    list(user_status.keys()) +
    list(user_threshold.keys()) +
    list(user_tiers.keys()) +
    list(user_expiry.keys()) +
    list(user_referral.keys()) +
    list(active_restart_set)
)

for uid in user_ids:
    combined[uid] = {
        "_id": uid,
        "tracking": user_tracking.get(uid, {}),
        "status": user_status.get(uid, False),
        "threshold": user_threshold.get(uid, 5.0),
        "tier": user_tiers.get(uid, "apprentice"),
        "expiry": user_expiry.get(uid),
        "referral": user_referral.get(uid, {}),
        "active_restart": uid in active_restart_set
    }

# Export merged output for bulk insert
with open("storage/data/combined_users_for_mongo.json", "w", encoding="utf-8") as out:
    json.dump(list(combined.values()), out, indent=2)

print(f"✅ Combined {len(combined)} users into 'combined_users_for_mongo.json'")
