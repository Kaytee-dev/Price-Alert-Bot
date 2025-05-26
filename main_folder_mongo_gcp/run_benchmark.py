import asyncio
import json
import time
import logging
from telegram.ext import ApplicationBuilder
from monitor import TokenPriceMonitor
import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols


import storage.history as history
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run():
    # Build bot application instance (no polling)
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # Inject test user tracking
    with open("divided_user_tracking.json") as f:
        users.USER_TRACKING = json.load(f)
    users.USER_STATUS = {uid: True for uid in users.USER_TRACKING}

    logger.info(f"👥 Simulating {len(users.USER_TRACKING)} users for benchmark")

    # 🛡️ Patch save functions to avoid writing to disk
    tokens.save_active_token_data = lambda: None
    history.save_token_history = lambda: None
    symbols.save_symbols_to_file = lambda: None

    # Monitor setup
   
    monitor = TokenPriceMonitor(
        app,
        chunk_size=25,
        notification_batch_size=20,
        max_concurrent_notifications=5,
        save_threshold=50, # Save after 50 changes
        max_save_delay=5   # Or after 5 cycles with pending changes
    )

    start = time.perf_counter()
    result = await monitor.run_monitoring_cycle()
    duration = time.perf_counter() - start

    logger.info(f"✅ Benchmark done. Success={result}, took {duration:.2f}s")

if __name__ == "__main__":
    asyncio.run(run())
