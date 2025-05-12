import hashlib, json
from util.utils import load_json, save_json
from config import TOKEN_HISTORY_FILE
import storage.users as users
from typing import List, Dict

TOKEN_DATA_HISTORY: Dict[str, List[dict]] = {}
LAST_SAVED_HASHES: Dict[str, str] = {}

def load_token_history():
    global TOKEN_DATA_HISTORY, LAST_SAVED_HASHES
    TOKEN_DATA_HISTORY = load_json(TOKEN_HISTORY_FILE, {}, "token history")

    for addr, history_list in TOKEN_DATA_HISTORY.items():
        if history_list:
            latest = history_list[0]
            hash_val = hashlib.md5(json.dumps(latest, sort_keys=True).encode()).hexdigest()
            LAST_SAVED_HASHES[addr] = hash_val

def save_token_history():
    all_tracked_addresses = set()
    for user_chains in users.USER_TRACKING.values():
            for chain_id, addresses in user_chains.items():
                if isinstance(addresses, list):
                    all_tracked_addresses.update(addresses)
    
    for addr in list(TOKEN_DATA_HISTORY.keys()):
        if addr not in all_tracked_addresses:
            del TOKEN_DATA_HISTORY[addr]
            LAST_SAVED_HASHES.pop(addr, None)

    save_json(TOKEN_HISTORY_FILE, TOKEN_DATA_HISTORY, "token history")

