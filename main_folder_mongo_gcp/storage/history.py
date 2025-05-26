import hashlib, json
import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
from typing import List, Dict
import logging
import storage.token_collection as token_collection
from pymongo import UpdateOne


TOKEN_DATA_HISTORY: Dict[str, List[dict]] = {}
ACTIVE_TOKEN_DATA: Dict[str, List[dict]] = {}
LAST_SAVED_HASHES: Dict[str, str] = {}

# Setup logging
logger = logging.getLogger(__name__)

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


async def save_token_history():
    """
    Save token history and simultaneously clean up unused tokens.
    Only tracked tokens are saved to TOKEN_COLLECTION.
    """
    # Get all tokens being tracked from TRACKED_TOKEN
    all_tracked_addresses = {
        address
        for chain_tokens in tokens.TRACKED_TOKENS.values()
        for address in chain_tokens
    }

    # Clean up any tokens no longer being tracked
    for addr in list(TOKEN_DATA_HISTORY.keys()):
        if addr not in all_tracked_addresses:
            del TOKEN_DATA_HISTORY[addr]
            LAST_SAVED_HASHES.pop(addr, None)

    # Prepare bulk updates for the database
    # Prepare updates for MongoDB
    updates = []
    for address, history in TOKEN_DATA_HISTORY.items():
        if address in all_tracked_addresses and history:
            # Extract metadata and sessions
            first_entry = history[0]
            chain_id = first_entry.get("chain_id", None)
            symbol = first_entry.get("symbol", None)

            # Prepare sessions data
            sessions = [
                {
                    "timestamp": entry["timestamp"],
                    "priceChange_m5": entry.get("priceChange_m5"),
                    "volume_m5": entry.get("volume_m5"),
                    "marketCap": entry.get("marketCap")
                }
                for entry in history
            ]

            # Add to updates
            updates.append(
                UpdateOne(
                    {"_id": address},  # Filter by the `_id` field
                    {
                        "$set": {
                            "sessions": sessions,
                            "hash": LAST_SAVED_HASHES.get(address, ""),
                            "address": address,
                            "chain_id": chain_id,
                            "symbol": symbol
                        }
                    },
                    upsert=True
                )
            )

    # Perform bulk write to persist the updates
    if updates:
        collection = token_collection.get_tokens_collection()
        await collection.bulk_write(updates)
        logger.info(f"✅ Persisted token history and metadata for {len(updates)} tokens.")

    logger.info(f"✅ Cleaned and saved token history for {len(TOKEN_DATA_HISTORY)} tokens.")


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

async def load_token_data():
    """
    Load data from TOKEN_COLLECTION and populate in-memory caches.
    """
    global TOKEN_DATA_HISTORY, ACTIVE_TOKEN_DATA, LAST_SAVED_HASHES

    # Fetch all token data from the database
    collection = token_collection.get_tokens_collection()

    # Fetch all token documents except the "tracked_token" document
    token_documents = [doc async for doc in collection.find({"_id": {"$ne": "tracked_token"}})]

    # Build caches
    for doc in token_documents:
        try:
            address = doc["address"]
            hash_key = doc["hash"]
            symbol = doc["symbol"]
            chain_id = doc["chain_id"]
            sessions = doc.get("sessions", [])

            # Populate TOKEN_DATA_HISTORY
            TOKEN_DATA_HISTORY[address] = [
                {
                    "timestamp": session["timestamp"],
                    "address": address,
                    "symbol": symbol,
                    "chain_id": chain_id,
                    "priceChange_m5": session.get("priceChange_m5"),
                    "volume_m5": session.get("volume_m5"),
                    "marketCap": session.get("marketCap")
                }
                for session in sessions
            ]

            # Populate LAST_SAVED_HASHES
            LAST_SAVED_HASHES[address] = hash_key

            # Populate ACTIVE_TOKEN_DATA (Example: Use a filter to check active tokens)
            # Replace with actual active token logic
            ACTIVE_TOKEN_DATA[address] = TOKEN_DATA_HISTORY[address]
        
        except KeyError as e:
            # Log and skip invalid documents
            logger.warning(f"Skipped document due to missing key: {e}. Document: {doc}")

    # If no saved hashes or missing entries, compute from history
    for addr, history_list in TOKEN_DATA_HISTORY.items():
        if history_list and addr not in LAST_SAVED_HASHES:
            latest = history_list[0]
            LAST_SAVED_HASHES[addr] = compute_data_hash(latest)
    
    logger.info(f"✅ Loaded token history for {len(TOKEN_DATA_HISTORY)} tokens with {len(LAST_SAVED_HASHES)} hashes")


async def remove_token_history(addresses: list[str]):
    """
    Remove token history for a list of token addresses from the caches and database.

    :param addresses: List of token addresses to remove.
    """
    global TOKEN_DATA_HISTORY

    collection = token_collection.get_tokens_collection()

    # Remove from TOKEN_DATA_HISTORY & associated data for unreferenced tokens
    for address in addresses:
        TOKEN_DATA_HISTORY.pop(address, None)
        LAST_SAVED_HASHES.pop(address, None)
        symbols.ADDRESS_TO_SYMBOL.pop(address, None)
    
    logger.info(f"✅ Cleanup complete for unreferenced tokens.")

    # Remove from the database
    if addresses:
        await collection.delete_many({"_id": {"$in": addresses}})

    logger.info(f"✅ Removed history and documents for {len(addresses)} tokens.")


