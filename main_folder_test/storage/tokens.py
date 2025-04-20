from utils import load_json, save_json
from config import TRACKED_TOKENS_FILE, ACTIVE_TOKENS_FILE
from typing import List

TRACKED_TOKENS: List[str] = []
ACTIVE_TOKEN_DATA = {}

def load_tracked_tokens():
    global TRACKED_TOKENS
    TRACKED_TOKENS = load_json(TRACKED_TOKENS_FILE, [], "tracked tokens")

def save_tracked_tokens():
    save_json(TRACKED_TOKENS_FILE, TRACKED_TOKENS, "tracked tokens")

def load_active_token_data():
    global ACTIVE_TOKEN_DATA
    ACTIVE_TOKEN_DATA = load_json(ACTIVE_TOKENS_FILE, {}, "active token data")

def save_active_token_data():
    save_json(ACTIVE_TOKENS_FILE, ACTIVE_TOKEN_DATA, "active token data")
