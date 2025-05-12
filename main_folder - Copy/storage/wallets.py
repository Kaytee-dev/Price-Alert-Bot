# wallets.py

import random
from typing import Optional, Dict
from util.utils import load_json, save_json
from config import WALLET_POOL_FILE


WALLET_LIST = []


def load_wallets():
    global WALLET_LIST
    data = load_json(WALLET_POOL_FILE, {}, "wallets")
    WALLET_LIST = data.get("wallets", [])
    initialize_wallet_statuses()


def save_wallets():
    save_json(WALLET_POOL_FILE, {"wallets": WALLET_LIST}, "wallets")


def get_random_wallet() -> Optional[str]:
    if not WALLET_LIST:
        load_wallets()
    available_wallets = [w for w in WALLET_LIST if w.get("status") == "available"]
    return random.choice(available_wallets)["address"] if available_wallets else None


def get_wallet_by_address(address: str) -> Optional[Dict]:
    for wallet in WALLET_LIST:
        if wallet.get("address") == address:
            return wallet
    return None


def set_wallet_status(address: str, status: str) -> bool:
    for wallet in WALLET_LIST:
        if wallet.get("address") == address:
            wallet["status"] = status
            save_wallets()
            return True
    return False


def initialize_wallet_statuses():
    updated = False
    for i, wallet in enumerate(WALLET_LIST):
        if isinstance(wallet, str):
            WALLET_LIST[i] = {"address": wallet, "status": "available"}
            updated = True
        elif "status" not in wallet:
            wallet["status"] = "available"
            updated = True

    if updated:
        save_wallets()


def revert_wallet_status_from_context(context) -> bool:
    wallet = context.user_data.get("payment_wallet")
    if wallet:
        return set_wallet_status(wallet, "available")
    return False

def mark_wallet_as_available(address: str):
    for wallet in WALLET_LIST:
        if wallet["address"] == address:
            wallet["status"] = "available"
            save_wallets()
            return True
    return False
