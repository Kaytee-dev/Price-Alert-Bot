from util.utils import load_json, save_json
from config import USER_TRACKING_FILE, USER_STATUS_FILE
import logging

USER_TRACKING = {}
USER_STATUS = {}

logger = logging.getLogger(__name__)

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

# def load_user_tracking():
#     """Load user tracking data from disk and migrate if needed."""
#     global USER_TRACKING
#     logger.debug("🚨 Inside load_user_tracking()")
#     data = load_json(USER_TRACKING_FILE, {}, "user tracking")
    
#     # Migrate old format if needed
#     migrated_data = {}
#     for user_id, tokens in data.items():
#         user_id = str(user_id)  # Ensure user_id is string
#         migrated_data[user_id] = {}
        
#         if isinstance(tokens, list):
#             # Previous format: list of tokens or token dicts
#             for token in tokens:
#                 if isinstance(token, str):
#                     # Legacy format: plain address string (assumed Solana)
#                     if 'solana' not in migrated_data[user_id]:
#                         migrated_data[user_id]['solana'] = []
#                     migrated_data[user_id]['solana'].append(token)
                    
#                 elif isinstance(token, dict) and 'chain_id' in token and 'address' in token:
#                     # Newer format: dict with chain_id and address
#                     chain_id = token['chain_id']
#                     address = token['address']
                    
#                     if chain_id not in migrated_data[user_id]:
#                         migrated_data[user_id][chain_id] = []
                    
#                     if address not in migrated_data[user_id][chain_id]:
#                         migrated_data[user_id][chain_id].append(address)
        
#         elif isinstance(tokens, dict):
#             # Might already be in the desired format
#             migrated_data[user_id] = tokens
    
#     USER_TRACKING = migrated_data
#     save_user_tracking()
#     return USER_TRACKING