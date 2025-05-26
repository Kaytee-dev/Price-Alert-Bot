import json
from pathlib import Path
from pymongo import MongoClient, UpdateOne

# MongoDB setup
client = MongoClient("mongodb+srv://kayteedev:Cve186538%40futa@telegrambot.cf7jq7p.mongodb.net/?retryWrites=true&w=majority&appName=TelegramBot&tls=true")
db = client["price_alert_bot"]
tokens_collection = db["tokens"]

# Load JSON files
base_path = Path("storage/data")

def load_json(filename):
    with open(base_path / filename, "r", encoding="utf-8") as f:
        return json.load(f)

# Input JSONs
token_tracking = load_json("tracked_tokens.json")
token_history = load_json("token_history.json")
symbols = load_json("symbols.json")
last_saved_hashes = load_json("last_saved_hashes.json")

# Combine for tracked tokens
tracked_token_doc = {
    "_id": "tracked_token",
    "token_list": {}
}

for chain_id, tokens in token_tracking.items():
    tracked_token_doc["token_list"][chain_id] = []
    for address in tokens:
        tracked_token_doc["token_list"][chain_id].append({
            "address": address,
            "symbol": symbols.get(address, "Unknown")
        })

# Combine for token history
token_history_docs = []
for token_address, sessions in token_history.items():
    if not sessions:
        continue

    
    symbol = None
    chain_id = None

    for session in sessions:
        symbol = session.get("symbol")
        chain_id = session.get("chain_id")
        if symbol and chain_id:
            break  # ✅ found valid session

    # # Extract static fields from the first session
    # first_session = sessions[0]
    # symbol = first_session["symbol"]
    # chain_id = first_session["chain_id"]

    # Remove static fields from sessions
    simplified_sessions = [
        {
            "timestamp": session["timestamp"],
            "priceChange_m5": session.get("priceChange_m5"),
            "volume_m5": session.get("volume_m5"),
            "marketCap": session.get("marketCap")
        }
        for session in sessions
    ]

    # Create token document
    token_doc = {
        "_id": token_address,
        "address": token_address,
        "symbol": symbol,
        "chain_id": chain_id,
        "hash": last_saved_hashes.get(token_address, ""),
        "sessions": simplified_sessions
    }
    token_history_docs.append(token_doc)

# Insert into MongoDB
bulk_operations = [
    UpdateOne({"_id": tracked_token_doc["_id"]}, {"$set": tracked_token_doc}, upsert=True)
]

for token_doc in token_history_docs:
    bulk_operations.append(
        UpdateOne({"_id": token_doc["_id"]}, {"$set": token_doc}, upsert=True)
    )

tokens_collection.bulk_write(bulk_operations)

print(f"✅ Migrated tokens to MongoDB with {len(bulk_operations)} operations.")
