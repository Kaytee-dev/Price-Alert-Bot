# test_payout_validation.py

import time
import requests
from solana.rpc.api import Client
from solders.pubkey import Pubkey # type: ignore

SOLSCAN_BASE = "https://solscan.io/account/{}"
SOLANA_CLIENT = Client("https://api.mainnet-beta.solana.com")


def is_valid_address_format(addr: str) -> bool:
    try:
        if not (32 <= len(addr) <= 44):
            return False
        Pubkey.from_string(addr)
        return True
    except Exception:
        return False


def is_indexed_by_solscan(addr: str) -> bool:
    try:
        url = SOLSCAN_BASE.format(addr)
        resp = requests.get(url, timeout=5)
        return resp.status_code != 404
    except Exception:
        return False


def validate_payout_addresses(raw_input: str):
    start_time = time.time()

    addresses_raw = raw_input.strip()
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        print("❌ No valid wallet addresses provided.")
        return

    added, failed = [], []

    for addr in addresses:
        if not is_valid_address_format(addr):
            failed.append((addr, "Invalid format or base58 length"))
            continue

        if is_indexed_by_solscan(addr):
            added.append(addr)
        else:
            failed.append((addr, "Not indexed on Solscan (likely inactive or never used)"))

    elapsed = round(time.time() - start_time, 2)

    print("\n--- Validation Results ---")
    if added:
        print("✅ Valid Wallets:")
        for a in added:
            print(f"  - {a}")
    if failed:
        print("⚠️ Invalid or Rejected:")
        for a, r in failed:
            print(f"  - {a}: {r}")

    print(f"\n⏱️ Validation completed in {elapsed} seconds")


if __name__ == "__main__":
    raw = input("Enter payout addresses (comma-separated): ")
    validate_payout_addresses(raw)
