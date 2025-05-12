from util.utils import load_json, save_json
from config import USER_TRACKING_FILE, USER_STATUS_FILE
import logging

USER_TRACKING = {}
USER_STATUS = {}

def load_user_tracking():
    global USER_TRACKING
    logging.debug("🚨 Inside load_user_tracking()")
    USER_TRACKING = load_json(USER_TRACKING_FILE, {}, "user tracking")

def save_user_tracking():
    save_json(USER_TRACKING_FILE, USER_TRACKING, "user tracking")

def load_user_status():
    global USER_STATUS
    USER_STATUS = load_json(USER_STATUS_FILE, {}, "user status")

def save_user_status():
    save_json(USER_STATUS_FILE, USER_STATUS, "user status")
