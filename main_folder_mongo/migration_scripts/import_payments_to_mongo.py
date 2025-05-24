# scripts/import_payments_to_mongo.py

import json
from pathlib import Path
from pymongo import MongoClient, UpdateOne

client = MongoClient("mongodb+srv://kayteedev:Cve186538%40futa@telegrambot.cf7jq7p.mongodb.net/?retryWrites=true&w=majority&appName=TelegramBot&tls=true")
db = client["price_alert_bot"]
payments_col = db["payments"]

base_path = Path("storage/data")

def load_json(filename):
    with open(base_path / filename, "r", encoding="utf-8") as f:
        return json.load(f)

# Load inputs
wallets_devnet = load_json("wallets_devnet.json")
wallets_secrets = load_json("wallets_secrets.json")
payout = load_json("payout.json")
payment_logs = load_json("payment_logs.json")

# Singleton documents
docs = [
    {
        "_id": "deposit_wallets",
        "wallets": wallets_devnet["wallets"]
    },
    {
        "_id": "wallet_secrets",
        "secrets": wallets_secrets
    },
    {
        "_id": "withdrawal_wallets",
        "wallets": payout
    }
]

# Per-user payment logs
for user_id, payments in payment_logs.items():
    docs.append({
        "_id": user_id,
        "payments": payments
    })

# Bulk write
bulk_ops = [
    UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    for doc in docs
]

payments_col.bulk_write(bulk_ops)
print(f"✅ Migrated {len(docs)} payment documents to MongoDB.")
