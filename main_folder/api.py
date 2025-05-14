# api.py
import logging
import asyncio
import httpx
from typing import List, Dict
from config import DEXSCREENER_API_BASE

logger = logging.getLogger(__name__)



async def fetch_prices_for_tokens(
    tokens: List[Dict],
    max_retries: int = 3,
    retry_delay: int = 2
) -> List[dict]:
    """
    Fetch prices for tokens grouped by chain ID asynchronously.

    Args:
        tokens: List of dicts with 'chain_id' and 'address' keys
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries (doubles each time)

    Returns:
        List of token data dictionaries
    """
    if not tokens:
        return []

    # Group tokens by chain_id
    chain_groups = {}
    for token in tokens:
        chain_id = token.get("chain_id")
        address = token.get("address")
        if chain_id and address:
            chain_groups.setdefault(chain_id, []).append(address)

    all_results = []

    # Process each chain group separately
    async with httpx.AsyncClient(timeout=10) as client:
        for chain_id, addresses in chain_groups.items():
            token_query = ",".join(addresses)
            # Updated URL format to support different chains
            url = f"{DEXSCREENER_API_BASE}/tokens/v1/{chain_id}/{token_query}"

            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"📡 Fetching data for {len(addresses)} tokens on {chain_id}")
                    response = await client.get(url)

                    if response.status_code == 200:
                        results = response.json()
                        # Add chain_id to each result for downstream processing
                        for result in results:
                            result["chainId"] = chain_id
                        all_results.extend(results)
                        break
                    else:
                        logger.warning(f"📡 Attempt {attempt}: Non-200 response ({response.status_code}) for chain {chain_id}")
                except httpx.RequestError as e:
                    logger.warning(f"🌐 Attempt {attempt}: Network error on chain {chain_id}: {e}")
                except Exception as e:
                    logger.warning(f"❌ Attempt {attempt}: Unexpected error on chain {chain_id}: {e}")

                if attempt < max_retries:
                    backoff = retry_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)
            else:
                logger.error(f"🚫 All retry attempts failed for chain {chain_id}")

    return all_results


async def get_token_chain_info(
    token_address: str,
    max_retries: int = 3,
    retry_delay: int = 2
) -> Dict:
    """
    Get chain ID and symbol for a token from DexScreener using async HTTP.

    Args:
        token_address: The token address to look up

    Returns:
        Dict with 'chain_id', 'symbol', and 'name' or empty dict if not found
    """
    url = f"{DEXSCREENER_API_BASE}/latest/dex/search?q={token_address}"

    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(url)

                if response.status_code == 200:
                    data = response.json()
                    pairs = data.get("pairs", [])

                    if pairs:
                        first_pair = pairs[0]
                        
                        return {
                            "chain_id": first_pair.get("chainId"),
                            "symbol": first_pair.get("baseToken", {}).get("symbol", ""),
                            "name": first_pair.get("baseToken", {}).get("name", "")
                        }
                else:
                    logger.warning(f"Attempt {attempt}: Non-200 response {response.status_code} for {token_address}")
            except httpx.RequestError as e:
                logger.warning(f"🌐 Attempt {attempt}: Network error: {e}")
            except Exception as e:
                logger.warning(f"❌ Attempt {attempt}: Unexpected error: {e}")

            if attempt < max_retries:
                backoff = retry_delay * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

    return {}
