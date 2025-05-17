import hashlib, json
from util.utils import load_json, save_json
from config import TOKEN_HISTORY_FILE, HASH_FILE
import storage.users as users
from typing import List, Dict
import logging

TOKEN_DATA_HISTORY: Dict[str, List[dict]] = {}
LAST_SAVED_HASHES: Dict[str, str] = {}

# Setup logging
logger = logging.getLogger(__name__)

# def load_token_history():
#     global TOKEN_DATA_HISTORY, LAST_SAVED_HASHES
#     TOKEN_DATA_HISTORY = load_json(TOKEN_HISTORY_FILE, {}, "token history")

#     for addr, history_list in TOKEN_DATA_HISTORY.items():
#         if history_list:
#             latest = history_list[0]
#             hash_val = hashlib.md5(json.dumps(latest, sort_keys=True).encode()).hexdigest()
#             LAST_SAVED_HASHES[addr] = hash_val

# def save_token_history():
#     all_tracked_addresses = set()
#     for user_chains in users.USER_TRACKING.values():
#             for chain_id, addresses in user_chains.items():
#                 if isinstance(addresses, list):
#                     all_tracked_addresses.update(addresses)
    
#     for addr in list(TOKEN_DATA_HISTORY.keys()):
#         if addr not in all_tracked_addresses:
#             del TOKEN_DATA_HISTORY[addr]
#             LAST_SAVED_HASHES.pop(addr, None)

#     save_json(TOKEN_HISTORY_FILE, TOKEN_DATA_HISTORY, "token history")

def compute_data_hash(data: dict) -> str:
    """
    Compute a hash for token data to detect changes.
    Excludes timestamp from hashing to detect actual data changes.
    """
    # Create a copy without timestamp to focus on actual data changes
    hash_base = {
        "address": data.get("address"),
        "symbol": data.get("symbol"),
        "priceChange_m5": data.get("priceChange_m5"),
        "volume_m5": data.get("volume_m5"),
        "marketCap": data.get("marketCap")
    }
    
    snapshot_json = json.dumps(hash_base, sort_keys=True)
    return hashlib.md5(snapshot_json.encode()).hexdigest()

def load_token_history():
    """
    Load token history and compute hashes for the latest entries.
    This ensures we have hash references even on first startup.
    """
    global TOKEN_DATA_HISTORY, LAST_SAVED_HASHES
    
    # Load the history data
    TOKEN_DATA_HISTORY = load_json(TOKEN_HISTORY_FILE, {}, "token history")
    
    # Try to load saved hashes first
    LAST_SAVED_HASHES = load_json(HASH_FILE, {}, "saved hashes")
    
    # If no saved hashes or missing entries, compute from history
    for addr, history_list in TOKEN_DATA_HISTORY.items():
        if history_list and addr not in LAST_SAVED_HASHES:
            latest = history_list[0]
            LAST_SAVED_HASHES[addr] = compute_data_hash(latest)
    
    logger.info(f"✅ Loaded token history for {len(TOKEN_DATA_HISTORY)} tokens with {len(LAST_SAVED_HASHES)} hashes")

def save_token_history():
    """
    Save token history and simultaneously clean up unused tokens.
    Only tracked tokens are saved to disk.
    """
    # Get all tokens being tracked by any user
    all_tracked_addresses = set()
    for user_chains in users.USER_TRACKING.values():
            for chain_id, addresses in user_chains.items():
                if isinstance(addresses, list):
                    all_tracked_addresses.update(addresses)

    # Clean up any tokens no longer being tracked
    for addr in list(TOKEN_DATA_HISTORY.keys()):
        if addr not in all_tracked_addresses:
            del TOKEN_DATA_HISTORY[addr]
            LAST_SAVED_HASHES.pop(addr, None)
    
    # Save the history data
    save_json(TOKEN_HISTORY_FILE, TOKEN_DATA_HISTORY, "token history")
    
    # Save the hashes
    save_json(HASH_FILE, LAST_SAVED_HASHES, "saved hashes")
    
    logger.info(f"✅ Saved token history and hashes for {len(TOKEN_DATA_HISTORY)} tokens")

def has_data_changed(address: str, data: dict) -> bool:
    """
    Check if the data for a token has changed compared to the last saved version.
    
    Args:
        address: Token address to check
        data: New token data to compare
        
    Returns:
        True if data has changed, False otherwise
    """
    # Calculate hash of the new data
    current_hash = compute_data_hash(data)
    
    # Check if we have a saved hash and if it matches
    saved_hash = LAST_SAVED_HASHES.get(address)
    if saved_hash is None:
        # No previous data for comparison
        return True
    
    return current_hash != saved_hash

def update_token_data(address: str, data: dict) -> bool:
    """
    Update token data in history if it has changed.
    
    Args:
        address: Token address to update
        data: New token data
        
    Returns:
        True if data was updated, False if unchanged
    """
    # Check if the token data has changed
    if not has_data_changed(address, data):
        return False
        
    # Data has changed, update the hash
    current_hash = compute_data_hash(data)
    LAST_SAVED_HASHES[address] = current_hash
    
    # Ensure the history container exists
    if address not in TOKEN_DATA_HISTORY:
        TOKEN_DATA_HISTORY[address] = []
    
    # Add the new data to history
    TOKEN_DATA_HISTORY[address].insert(0, data)
    
    # Keep only the latest 3 entries
    TOKEN_DATA_HISTORY[address] = TOKEN_DATA_HISTORY[address][:3]
    
    return True

# Initialize the module
#load_token_history()