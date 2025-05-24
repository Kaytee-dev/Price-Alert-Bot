import json
from pathlib import Path

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
            "address": address, "symbol": symbols.get(address, "Unknown")
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
            break

    simplified_sessions = [
        {
            "timestamp": session["timestamp"],
            "priceChange_m5": session.get("priceChange_m5"),
            "volume_m5": session.get("volume_m5"),
            "marketCap": session.get("marketCap")
        }
        for session in sessions
    ]

    token_doc = {
        "_id": token_address,
        "address": token_address,
        "symbol": symbol,
        "chain_id": chain_id,
        "md5_hash": last_saved_hashes.get(token_address, ""),
        "sessions": simplified_sessions
    }
    token_history_docs.append(token_doc)

# Output combined token data
combined = {
    "tracked_token": tracked_token_doc,
    "token_history": token_history_docs
}

with open(base_path / "combined_tokens_for_mongo.json", "w", encoding="utf-8") as out:
    json.dump(combined, out, indent=2)

print(f"✅ Combined token data saved to 'combined_tokens_for_mongo.json'")
