import secrets_key as secrets_key
import storage.wallets as wallets
import logging

def sync_wallets_from_secrets():
    existing_addresses = {wallet["address"] for wallet in wallets.WALLET_LIST}

    for address in secrets_key.DECRYPTED_WALLETS:
        if address not in existing_addresses:
            wallets.WALLET_LIST.append({
                "address": address,
                "status": "available"
            })

    wallets.save_wallets()

def purge_orphan_wallets():
    valid_addresses = set(secrets_key.DECRYPTED_WALLETS)
    before = len(wallets.WALLET_LIST)
    wallets.WALLET_LIST[:] = [w for w in wallets.WALLET_LIST if w["address"] in valid_addresses]
    after = len(wallets.WALLET_LIST)
    if before != after:
        wallets.save_wallets()
        logging.info(f"🧹 Purged {before - after} orphan wallets from pool.")
