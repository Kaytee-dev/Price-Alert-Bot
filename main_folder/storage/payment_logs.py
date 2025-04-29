import json
from datetime import datetime
from config import PAYMENT_LOGS_FILE
from utils import load_json, save_json

PAYMENT_LOGS = {}  # In-memory: {user_id: {payment_id: data}}


def load_payment_logs():
    global PAYMENT_LOGS
    PAYMENT_LOGS = load_json(PAYMENT_LOGS_FILE, {}, "payment log")


def save_payment_logs():
    save_json(PAYMENT_LOGS_FILE, PAYMENT_LOGS, "payment log")


def log_user_payment(user_id: int, payment_id: str, data: dict) -> None:
    """Store a user's payment attempt under their ID and payment_id."""
    user_key = str(user_id)
    if user_key not in PAYMENT_LOGS:
        PAYMENT_LOGS[user_key] = {}

    PAYMENT_LOGS[user_key][payment_id] = {
        **data,
        "logged_at": datetime.now().isoformat()
    }
    save_payment_logs()


def get_user_payment(user_id: int, payment_id: str) -> dict | None:
    return PAYMENT_LOGS.get(str(user_id), {}).get(payment_id)


def find_payment_globally(payment_id: str) -> tuple[str, dict] | None:
    for uid, payments in PAYMENT_LOGS.items():
        if payment_id in payments:
            return uid, payments[payment_id]
    return None
