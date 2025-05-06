from util.utils import load_json, save_json
from config import USER_THRESHOLDS_FILE
from typing import Dict

USER_THRESHOLDS: Dict[str, float] = {}


def load_user_thresholds():
    global USER_THRESHOLDS
    USER_THRESHOLDS = load_json(USER_THRESHOLDS_FILE, {}, "user thresholds")


def save_user_thresholds():
    save_json(USER_THRESHOLDS_FILE, USER_THRESHOLDS, "user thresholds")
