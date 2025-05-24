# token_alert_bot.py

import asyncio
import logging
import os
import sys

from telegram import Update, BotCommand, BotCommandScopeDefault
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, TypeHandler
)

from config import (
    BOT_TOKEN, RESTART_FLAG_FILE, ACTIVE_RESTART_USERS_FILE, SUPER_ADMIN_ID
)

from commands import (
    start, stop, add, remove, list_tokens, reset, help_command, 
    status, restart, alltokens, threshold, handle_dashboard_button, launch,
    handle_list_navigation, callback_reset_confirmation, back_to_dashboard
)


import storage.tokens
import storage.users
from storage.tiers import load_user_tiers, check_and_process_tier_expiry_scheduler
import storage.tiers as tiers
import storage.thresholds as thresholds


from storage.tokens import load_tracked_tokens, load_active_token_data
from storage.symbols import load_symbols_from_file
from storage.users import load_user_tracking, load_user_status, save_user_status
from storage.history import load_token_history

from storage.expiry import load_user_expiry
from storage.notify import remind_inactive_users
from storage.payment_logs import load_payment_logs
from storage.wallets import load_wallets
from storage.payout import load_payout_wallets

from util.wallet_sync import sync_wallets_from_secrets, purge_orphan_wallets
from secrets_key import load_encrypted_keys


from admin import (
    addadmin, removeadmin, listadmins,
    handle_removeadmin_callback, load_admins, ADMINS, addwallet, addpayout,
    check_payment_conv, manual_upgrade_conv, list_referrals, register_wallet_commands
)
from util.utils import (load_json, save_json, send_message,
                   refresh_user_commands
                   )
from monitor import background_price_monitor

from upgrade import upgrade_conv_handler
from referral import register_referral_handlers
from renewal import renewal_conv_handler
from referral_payout import register_payout_handlers
from util.error_logs import error_handler
from storage.rpcs import load_rpc_list



logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)



async def callback_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_restart":
        await query.edit_message_text("♻️ Restarting bot...")
        admin_id = query.from_user.id

        async def safe_restart():
            try:
                if not getattr(context.application, "_monitor_started", False):
                    logger.info("ℹ️ Monitor was never started — skipping restart logic.")
                    await send_message(
                        context.bot,
                        "ℹ️ Restart aborted — monitor loop was never started.",
                        chat_id=admin_id
                    )
                    return

                active_users = [user_id for user_id, status in storage.users.USER_STATUS.items() if status]
                save_json(ACTIVE_RESTART_USERS_FILE, active_users, "active restart users")
                save_json(RESTART_FLAG_FILE, {"from_restart": True}, "restart flag")

                for user_id in storage.users.USER_STATUS:
                    storage.users.USER_STATUS[user_id] = False
                save_user_status()

                if hasattr(context.application, "_monitor_task"):
                    task = context.application._monitor_task
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    else:
                        logger.info("ℹ️ Monitor task exists but already completed.")
                else:
                    logger.warning("⚠️ Monitor task reference missing despite start flag — possible inconsistency.")

                # Cancelling expiry task scheduler
                if hasattr(context.application, "_expiry_task"):
                    task = context.application._expiry_task
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                
                # Cancelling inactive users reminder task scheduler
                if hasattr(context.application, "_reminder_task"):
                    task = context.application._reminder_task
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                await context.application.stop()
                await asyncio.sleep(1)

                logger.info("🔁 Restarting...")
            except Exception as e:
                logger.error(f"Restart error: {e}")
            finally:
                os.execl(sys.executable, sys.executable, *sys.argv)

        asyncio.create_task(safe_restart())

    elif query.data == "cancel_restart":
        await query.edit_message_text("❌ Restart cancelled.")


async def callback_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_stop":
        await query.edit_message_text("🔌 Shutting down bot...")

        async def safe_shutdown():
            try:

                 # ✅ Save current active users
                active_users = [user_id for user_id, status in storage.users.USER_STATUS.items() if status]
                save_json(ACTIVE_RESTART_USERS_FILE, active_users, "active restart users")
                save_json(RESTART_FLAG_FILE, {"from_restart": True}, "restart flag")

                # ✅ Reset all statuses
                for user_id in storage.users.USER_STATUS:
                    storage.users.USER_STATUS[user_id] = False
                save_user_status()

                # ✅ Cancel monitor loop
                if hasattr(context.application, "_monitor_task"):
                    task = context.application._monitor_task
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                
                # Cancelling expiry task scheduler
                if hasattr(context.application, "_expiry_task"):
                    task = context.application._expiry_task
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                
                # Cancelling inactive users reminder task scheduler
                if hasattr(context.application, "_reminder_task"):
                    task = context.application._reminder_task
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                await context.application.stop()

                # ✅ Cancel all running tasks
                tasks = asyncio.all_tasks()
                for task in tasks:
                    if task is not asyncio.current_task():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                await asyncio.sleep(1)
                logger.info("🔌 Bot stopped cleanly.")
            except Exception as e:
                logger.error(f"Shutdown error: {e}")
            finally:
                os._exit(0)

        asyncio.create_task(safe_shutdown())

    elif query.data == "cancel_stop":
        await query.edit_message_text("❌ Shutdown cancelled.")


# --- Bot Runner ---
async def on_startup(app):
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


    # 🔧 Set fallback default commands
    default_cmds = [
        BotCommand("lc", "Launch bot dashboard"),
        BotCommand("start", "Start tracking tokens"),
        BotCommand("stop", "Stop tracking tokens"),
        BotCommand("add", "Add a token to track -- /a"),
        BotCommand("remove", "Remove token from tracking -- /rm"),
        BotCommand("list", "List tracked tokens -- /l"),
        BotCommand("reset", "Clear all tracked tokens -- /x"),
        BotCommand("help", "Show help message -- /h"),
        BotCommand("status", "Show stats of tracked tokens -- /s"),
        BotCommand("threshold", "Set your spike alert threshold (%) -- /t"),
    ]
    await app.bot.set_my_commands(default_cmds, scope=BotCommandScopeDefault())

    # 🔧 Re-apply scoped commands for all admins
    for admin_id in ADMINS:
        await refresh_user_commands(admin_id, app.bot)

    # 🔧 Also refresh super admin's scoped menu
    await refresh_user_commands(SUPER_ADMIN_ID, app.bot)

async def extract_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Middleware: Save username globally into context.bot_data."""
    if update.effective_user:
        user = update.effective_user
        username = f"@{user.username}" if user.username else user.full_name
        chat_id = str(update.effective_user.id)

        if "usernames" not in context.bot_data:
            context.bot_data["usernames"] = {}
        context.bot_data["usernames"][chat_id] = username


def main():
    # 🚀 Core Launch Commands
    load_admins()
    load_user_tracking()
    load_user_status()

    load_symbols_from_file()
    
    load_tracked_tokens()
    load_token_history()
    load_active_token_data()
    load_user_tiers()
    load_user_expiry()
    load_payment_logs()
    load_payout_wallets()
    load_wallets()
    load_encrypted_keys()
    sync_wallets_from_secrets()
    purge_orphan_wallets()
    load_rpc_list()

    # 🔒 Enforce token limits based on user tiers
    for user_id_str in list(storage.users.USER_TRACKING.keys()):
        tiers.enforce_token_limit_core(int(user_id_str))
    
    

    # Restore active users if bot restarted via /restart
    restart_flag = load_json(RESTART_FLAG_FILE, {}, "restart flag")
    if restart_flag.get("from_restart"):
        active_users = load_json(ACTIVE_RESTART_USERS_FILE, [], "active restart users")
        for user_id in active_users:
            storage.users.USER_STATUS[user_id] = True
        storage.users.save_user_status()
        try:
            os.remove(ACTIVE_RESTART_USERS_FILE)
            os.remove(RESTART_FLAG_FILE)
            logger.info("🧹 Cleaned up restart state files.")
        except Exception as e:
            logger.warning(f"⚠️ Failed to clean restart state files: {e}")

    # 🧮 Token Tracking — Rebuild from loaded structured USER_TRACKING
    grouped_tokens = {}
    for token_dict in storage.users.USER_TRACKING.values():
        for chain_id, addresses in token_dict.items():
            grouped_tokens.setdefault(chain_id, set()).update(addresses)

    # Convert sets to sorted lists
    grouped_tokens = {k: sorted(v) for k, v in grouped_tokens.items()}

    storage.tokens.TRACKED_TOKENS = grouped_tokens
    storage.tokens.save_tracked_tokens()
    logger.info(f"🔁 Rebuilt tracked tokens list across {len(grouped_tokens)} chains.")

    # Adding threshold on startup
    thresholds.load_user_thresholds()
    updated = False
    for chat_id in storage.users.USER_TRACKING:
        if chat_id not in thresholds.USER_THRESHOLDS:
            thresholds.USER_THRESHOLDS[chat_id] = 5.0
            updated = True
    if updated:
        thresholds.save_user_thresholds()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )

    app.bot_data["launch_dashboard"] = launch
    app.add_error_handler(error_handler)

    app.add_handler(TypeHandler(Update, extract_username), group=-999)
    app.add_handler(CommandHandler("lc", launch))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))

    app.add_handler(CommandHandler(["add", "a"], add))
    app.add_handler(CommandHandler(["alltokens", "at"], alltokens))

    app.add_handler(CommandHandler(["remove", "rm"], remove))
    app.add_handler(CommandHandler(["list", "l"], list_tokens))

    app.add_handler(CommandHandler(["reset", "x"], reset))
    app.add_handler(CommandHandler(["help", "h"], help_command))

    app.add_handler(CommandHandler(["restart", "rs"], restart))
    app.add_handler(CommandHandler(["status", "s"], status))

    app.add_handler(CommandHandler(["addadmin", "aa"], addadmin))
    app.add_handler(CommandHandler(["removeadmin", "ra"], removeadmin))

    app.add_handler(CommandHandler(["listadmins", "la"], listadmins))
    app.add_handler(CommandHandler("aw", addwallet))

    app.add_handler(CommandHandler("ap", addpayout))
    app.add_handler(CommandHandler(["listrefs", "lr"], list_referrals))

    app.add_handler(CommandHandler("threshold", threshold))
    app.add_handler(CommandHandler("t", threshold))

    app.add_handler(CallbackQueryHandler(callback_restart, pattern="^confirm_restart$|^cancel_restart$"))
    app.add_handler(CallbackQueryHandler(callback_stop, pattern="^confirm_stop$|^cancel_stop$"))
    app.add_handler(CallbackQueryHandler(callback_reset_confirmation, pattern="^confirm_reset$|^cancel_reset$"))
    app.add_handler(CallbackQueryHandler(handle_removeadmin_callback, pattern="^confirm_removeadmin:|^cancel_removeadmin$"))

    app.add_handler(CallbackQueryHandler(back_to_dashboard, pattern="^go_to_dashboard$"))
    app.add_handler(CallbackQueryHandler(handle_list_navigation, pattern="^list_prev$|^list_next$|^back_to_dashboard$"))

    app.add_handler(upgrade_conv_handler)
    app.add_handler(renewal_conv_handler)

    app.add_handler(CallbackQueryHandler(handle_dashboard_button, pattern="^cmd_"))
    register_referral_handlers(app)

    app.add_handler(check_payment_conv)
    app.add_handler(manual_upgrade_conv)

    register_wallet_commands(app)
    register_payout_handlers(app)
    app.run_polling()

if __name__ == "__main__":
    main()
