# payout.py

import random
from typing import List, Optional
from config import PAYOUT_WALLETS_FILE
from util.utils import load_json, save_json

PAYOUT_WALLETS: List[str] = []


def load_payout_wallets():
    global PAYOUT_WALLETS
    PAYOUT_WALLETS = load_json(PAYOUT_WALLETS_FILE, [], "payout wallets")


def save_payout_wallets():
    save_json(PAYOUT_WALLETS_FILE, PAYOUT_WALLETS, "payout wallets")


def add_wallet_to_payout_list(address: str) -> bool:
    """Adds a payout wallet address to the list if not already present."""
    if address not in PAYOUT_WALLETS:
        PAYOUT_WALLETS.append(address)
        save_payout_wallets()
        return True
    return False


def get_next_payout_wallet() -> Optional[str]:
    if not PAYOUT_WALLETS:
        load_payout_wallets()
    return random.choice(PAYOUT_WALLETS) if PAYOUT_WALLETS else None
