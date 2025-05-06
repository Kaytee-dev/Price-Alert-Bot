# api.py
import logging
import requests
import time
from typing import List

logger = logging.getLogger(__name__)

def fetch_prices_for_tokens(addresses: List[str], max_retries: int = 3, retry_delay: int = 2) -> List[dict]:
    token_query = ",".join(addresses)
    url = f"https://api.dexscreener.com/tokens/v1/solana/{token_query}"

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"📡 Attempt {attempt}: Non-200 response ({response.status_code})")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
            logger.warning(f"🌐 Attempt {attempt}: Network error: {net_err}")
        except requests.exceptions.RequestException as req_err:
            logger.warning(f"⚠️ Attempt {attempt}: General request failure: {req_err}")
        except Exception as e:
            logger.warning(f"❌ Attempt {attempt}: Unexpected error: {e}")

        if attempt < max_retries:
            backoff = retry_delay * (2 ** (attempt - 1))
            time.sleep(backoff)

    logger.error("🚫 All retry attempts failed.")
    return []
