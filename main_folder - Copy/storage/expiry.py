from util.utils import load_json, save_json
from config import USER_EXPIRY_FILE
from typing import Dict

USER_EXPIRY: Dict[str, str] = {}

def load_user_expiry():
    global USER_EXPIRY
    USER_EXPIRY = load_json(USER_EXPIRY_FILE, {}, "user expiry data")

def save_user_expiry():
    save_json(USER_EXPIRY_FILE, USER_EXPIRY, "user expiry data")
