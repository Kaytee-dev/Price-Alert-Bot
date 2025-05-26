from pymongo import MongoClient
import json
from mongo_client import MONGO_URI
from pathlib import Path

base_path = Path("storage/data")
client = MongoClient(MONGO_URI)
db = client["price_alert_bot"]
collection = db["users"]

def load_json(filename):
    with open(base_path / filename, "r", encoding="utf-8") as f:
        return json.load(f)

users = load_json("combined_users_for_mongo.json")
collection.insert_many(users)

print("✅ Inserted", len(users), "users.")
