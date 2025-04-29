import random
import json
from utils import load_json
from config import WALLET_POOL_FILE

WALLET_LIST = []


def load_wallets():
    global WALLET_LIST
    data = load_json(WALLET_POOL_FILE, {}, "wallets")
    WALLET_LIST = data.get("wallets", [])


def get_random_wallet() -> str:
    if not WALLET_LIST:
        load_wallets()
    return random.choice(WALLET_LIST) if WALLET_LIST else None
