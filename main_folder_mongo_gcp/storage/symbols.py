import storage.token_collection as token_collection
from typing import Dict
import logging

ADDRESS_TO_SYMBOL: Dict[str, str] = {}

logger = logging.getLogger(__name__)

def load_symbols():
    """
    Load the symbols from TOKEN_COLLECTION and update the cache with address-symbol pairs.
    """
    global ADDRESS_TO_SYMBOL
    
    # Fetch tracked tokens from token_collection
    tracked_tokens = token_collection.get_tracked_tokens()

    # Build ADDRESS_TO_SYMBOL from tracked tokens
    ADDRESS_TO_SYMBOL = {
        token["address"]: token["symbol"]
        for chain_tokens in tracked_tokens.values()
        for token in chain_tokens
    }

    logger.info("✅ ADDRESS_TO_SYMBOL loaded and updated from token_collection")

