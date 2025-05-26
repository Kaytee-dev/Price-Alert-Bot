# api.py
import logging
import requests
import time
from typing import List, Dict

logger = logging.getLogger(__name__)

def fetch_prices_for_tokens(tokens: List[Dict], max_retries: int = 3, retry_delay: int = 2) -> List[dict]:
    """
    Fetch prices for tokens grouped by chain ID
    
    Args:
        tokens: List of dicts with 'chain_id' and 'address' keys
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries (will be exponentially increased)
    
    Returns:
        List of token data dictionaries
    """
    if not tokens:
        return []
    
    # Group tokens by chain_id
    chain_groups = {}
    for token in tokens:
        chain_id = token.get('chain_id')
        address = token.get('address')
        if chain_id and address:
            if chain_id not in chain_groups:
                chain_groups[chain_id] = []
            chain_groups[chain_id].append(address)
    
    all_results = []
    
    # Process each chain group separately
    for chain_id, addresses in chain_groups.items():
        token_query = ",".join(addresses)
        # Updated URL format to support different chains
        url = f"https://api.dexscreener.com/tokens/v1/{chain_id}/{token_query}"
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"📡 Fetching data for {len(addresses)} tokens on {chain_id}")
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    results = response.json()
                    # Add chain_id to each result for downstream processing
                    for result in results:
                        result["chainId"] = chain_id
                    all_results.extend(results)
                    break
                else:
                    logger.warning(f"📡 Attempt {attempt}: Non-200 response ({response.status_code}) for chain {chain_id}")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
                logger.warning(f"🌐 Attempt {attempt}: Network error on chain {chain_id}: {net_err}")
            except requests.exceptions.RequestException as req_err:
                logger.warning(f"⚠️ Attempt {attempt}: General request failure on chain {chain_id}: {req_err}")
            except Exception as e:
                logger.warning(f"❌ Attempt {attempt}: Unexpected error on chain {chain_id}: {e}")

            if attempt < max_retries:
                backoff = retry_delay * (2 ** (attempt - 1))
                time.sleep(backoff)
        else:
            logger.error(f"🚫 All retry attempts failed for chain {chain_id}.")
    
    return all_results

def get_token_chain_info(token_address: str) -> Dict:
    """
    Query DexScreener search endpoint to get chain ID and symbol for a token address
    
    Args:
        token_address: The token address to look up
    
    Returns:
        Dictionary with chain_id and symbol (or empty dict if not found)
    """
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            
            if pairs:
                first_pair = pairs[0]
                chain_id = first_pair.get("chainId")
                symbol = first_pair.get("baseToken", {}).get("symbol", "")
                name = first_pair.get("baseToken", {}).get("name", "")
                
                return {
                    "chain_id": chain_id,
                    "symbol": symbol,
                    "name": name
                }
    except Exception as e:
        logger.error(f"Error getting token chain info: {e}")
    
    return {}