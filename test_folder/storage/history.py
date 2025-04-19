import hashlib, json
import logging
from utils import load_json, save_json
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
    all_tracked_tokens = set(addr for tokens_list in users.USER_TRACKING.values() for addr in tokens_list)
    for addr in list(TOKEN_DATA_HISTORY.keys()):
        if addr not in all_tracked_tokens:
            del TOKEN_DATA_HISTORY[addr]
            LAST_SAVED_HASHES.pop(addr, None)

    save_json(TOKEN_HISTORY_FILE, TOKEN_DATA_HISTORY, "token history")

