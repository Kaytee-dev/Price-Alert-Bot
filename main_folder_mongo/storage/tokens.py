import storage.token_collection as token_collection
from typing import List, Dict
import logging



TRACKED_TOKENS = []

logger = logging.getLogger(__name__)

def load_tracked_tokens():
    """
    Load the tracked tokens from the in-memory cache or the database and format the structure for TRACKED_TOKENS.
    """
    global TRACKED_TOKENS
    
    # Fetch tracked tokens from token_collection
    raw_tracked_tokens = token_collection.get_tracked_tokens()

    # Format the structure for TRACKED_TOKENS
    TRACKED_TOKENS = {
        chain_id: [token["address"] for token in tokens]
        for chain_id, tokens in raw_tracked_tokens.items()
    }

    logger.info("✅ TRACKED TOKENS loaded and formatted from token_collection")


async def append_to_tracked_tokens(updates: list[dict]):
    """
    Append tokens to the tracked token list and synchronize both TRACKED_TOKEN and TOKEN_COLLECTION.
    
    :param updates: List of updates in the format:
        [
            {"bsc": [{"address": "0x123...", "symbol": "Token1"}, ...]},
            {"ethereum": [{"address": "0xabc...", "symbol": "Token3"}, ...]}
        ]
    """
    global TRACKED_TOKENS

    # Fetch the current state of tracked tokens
    current_tracked = token_collection.get_tracked_tokens()

    # Update TOKEN_COLLECTION
    for chain_update in updates:
        for chain_id, new_tokens in chain_update.items():
            # Ensure chain exists in TOKEN_COLLECTION
            if chain_id not in current_tracked:
                current_tracked[chain_id] = []

            # Add tokens, avoiding duplicates
            existing_addresses = {token["address"] for token in current_tracked[chain_id]}
            for token in new_tokens:
                if token["address"] not in existing_addresses:
                    current_tracked[chain_id].append(token)

    # Persist updated TOKEN_COLLECTION
    await token_collection.save_tracked_tokens(current_tracked)

    # Update TRACKED_TOKEN
    for chain_id, tokens in current_tracked.items():
        TRACKED_TOKENS[chain_id] = [token["address"] for token in tokens]

def rebuild_tracked_token():
    """
    Rebuild the TRACKED_TOKEN cache from TOKEN_COLLECTION.
    """
    global TRACKED_TOKEN

    # Fetch the current state of tracked tokens
    current_tracked = token_collection.get_tracked_tokens()

    # Rebuild TRACKED_TOKEN
    TRACKED_TOKEN = {
        chain_id: [token["address"] for token in tokens]
        for chain_id, tokens in current_tracked.items()
    }

    # Calculate statistics
    num_chains = len(TRACKED_TOKEN)
    num_tokens = sum(len(tokens) for tokens in TRACKED_TOKEN.values())

    # Log the rebuild details
    logger.info(f"🔁 Rebuilt tracked tokens list across {num_chains} chains with a total of {num_tokens} tokens.")