import mongo_client
import storage.user_collection as user_collection
import storage.token_collection as token_collection
from storage.history import load_token_data
import storage.payment_collection as payment_collection
from storage.users import load_user_tracking

from storage.symbols import load_symbols
from storage.tokens import load_tracked_tokens
from storage.payment_logs import load_payment_logs
from storage.payout import load_payout_wallets
from storage.wallets import load_wallets

from secrets_key import load_encrypted_keys
from util.wallet_sync import sync_wallets_from_secrets, purge_orphan_wallets
from storage.rpcs import load_rpc_list
from storage.notify import ensure_notify_records_for_active_users, remind_inactive_users

import storage.tiers as tiers
import util. restart_recovery as restart_recovery
import storage.tokens
import storage.thresholds as thresholds

import storage.users
from monitor import background_price_monitor
from storage.tiers import check_and_process_tier_expiry_scheduler
import logging

logger = logging.getLogger(__name__)


async def perform_boot_tasks(app):
    logger.info("🚀 perform_boot_tasks() started")


    await mongo_client.connect()
    logger.info("✅ MongoDB connected successfully")

    await user_collection.load_user_collection_from_mongo()
    await user_collection.ensure_user_indexes()

    await token_collection.load_token_collection_from_mongo()
    await token_collection.create_token_list_index()
    await load_token_data()

    await payment_collection.load_payment_collection_from_mongo()

    load_user_tracking()

    load_symbols
    load_tracked_tokens()

    await load_payment_logs()
    load_payout_wallets()

    await load_wallets()
    await load_encrypted_keys()
    await sync_wallets_from_secrets()
    await purge_orphan_wallets()
    await load_rpc_list()
    await ensure_notify_records_for_active_users()

    # 🔒 Enforce token limits based on user tiers
    await tiers.enforce_token_limits_bulk()
    
    # ♻️ Restore active restart users
    await restart_recovery.restore_active_users()

    # 🧮 Token Tracking — Rebuild from loaded structured USER_TRACKING
    storage.tokens.rebuild_tracked_token()
    
    # Adding threshold on startup
    await thresholds.load_user_thresholds()
    updated = False
    for chat_id in storage.users.USER_TRACKING:
        if chat_id not in thresholds.USER_THRESHOLDS:
            thresholds.USER_THRESHOLDS[chat_id] = 5.0
            updated = True
    if updated:
        await thresholds.save_user_thresholds()

    print("🔄 Starting background tasks...")

    if any(storage.users.USER_STATUS.values()):
        monitor_task = app.create_task(background_price_monitor(app))
        app._monitor_task = monitor_task
        app._monitor_started = True
        logger.info("🔄 Monitor loop auto-started after restart recovery.")

    # 📣 Also start the inactive user reminder loop
    reminder_task = app.create_task(remind_inactive_users(app))
    app._reminder_task = reminder_task
    logger.info("🔔 Inactive user reminder loop started.")

    # 🕒 Start the tier expiry check scheduler
    expiry_task = app.create_task(check_and_process_tier_expiry_scheduler(app))
    app._expiry_task = expiry_task
    logger.info("🔄 Tier expiry check scheduler started (2-day interval)")

    logger.info("✅ perform_boot_tasks() complete")

