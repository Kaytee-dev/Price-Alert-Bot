# test_payout_validation.py

from solana.rpc.api import Client
from solders.pubkey import Pubkey # type: ignore


def validate_payout_addresses(raw_input: str):
    addresses_raw = raw_input.strip()
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        print("❌ No valid wallet addresses provided.")
        return

    client = Client("https://api.mainnet-beta.solana.com")
    added, failed = [], []

    for addr in addresses:
        if len(addr) < 32 or len(addr) > 44:
            failed.append((addr, "Invalid length"))
            continue

        try:
            resp = client.get_account_info(Pubkey.from_string(addr))
            if resp.value is not None:
                added.append(addr)
            else:
                failed.append((addr, "Wallet not found on-chain"))
        except Exception as e:
            failed.append((addr, str(e)))

    print("\n--- Validation Results ---")
    if added:
        print("✅ Valid Wallets:")
        for a in added:
            print(f"  - {a}")
    if failed:
        print("⚠️ Invalid or Rejected:")
        for a, r in failed:
            print(f"  - {a}: {r}")


if __name__ == "__main__":
    raw = input("Enter payout addresses (comma-separated): ")
    validate_payout_addresses(raw)
