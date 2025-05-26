# scripts/export_payments_json.py

import json
from pathlib import Path

base_path = Path("storage/data")

def load_json(filename):
    with open(base_path / filename, "r", encoding="utf-8") as f:
        return json.load(f)

# Load inputs
wallets_devnet = load_json("wallets_devnet.json")
wallets_secrets = load_json("wallets_secrets.json")
payout = load_json("payout.json")
payment_logs = load_json("payment_logs.json")

# Compose base singleton documents
deposit_wallets_doc = {
    "_id": "deposit_wallets",
    "wallets": wallets_devnet["wallets"]
}

wallet_secrets_doc = {
    "_id": "wallet_secrets",
    "secrets": wallets_secrets
}

withdrawal_wallets_doc = {
    "_id": "withdrawal_wallets",
    "wallets": payout
}

# User-specific payment docs
payment_user_docs = []
for user_id, payments in payment_logs.items():
    payment_user_docs.append({
        "_id": user_id,
        "user_id": user_id,
        "payments": payments
    })

# Combine all
combined = {
    "deposit_wallets": deposit_wallets_doc,
    "wallet_secrets": wallet_secrets_doc,
    "withdrawal_wallets": withdrawal_wallets_doc,
    "user_payment_logs": payment_user_docs
}

with open(base_path / "combined_payments_for_mongo.json", "w", encoding="utf-8") as out:
    json.dump(combined, out, indent=2)

print("✅ Saved combined payment data to 'combined_payments_for_mongo.json'")
