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

from config import SUPER_ADMIN_ID

from commands import (
    start, stop, add, remove, list_tokens, reset, help_command, 
    status, restart, alltokens, threshold, handle_dashboard_button, launch,
    handle_list_navigation, callback_reset_confirmation, back_to_dashboard
)


import storage.tokens
import storage.users
from storage.tiers import check_and_process_tier_expiry_scheduler
import storage.tiers as tiers
import storage.thresholds as thresholds


from storage.tokens import load_tracked_tokens
from storage.symbols import load_symbols
from storage.users import load_user_tracking
from storage.history import load_token_data
from storage.rpcs import load_rpc_list


from storage.notify import remind_inactive_users
from storage.payment_logs import load_payment_logs
from storage.wallets import load_wallets
from storage.payout import load_payout_wallets

from util.wallet_sync import sync_wallets_from_secrets, purge_orphan_wallets
from secrets_key import load_encrypted_keys


from admin import (
    addadmin, removeadmin, listadmins,
    handle_removeadmin_callback, load_admins, addwallet, addpayout,
    check_payment_conv, manual_upgrade_conv, list_referrals, register_wallet_commands,
    addrpc, removerpc, listrpc, handle_removerpc_callback
)
from util.utils import (send_message,
                   refresh_user_commands, ADMINS
                   )
from monitor import background_price_monitor

from upgrade import upgrade_conv_handler, start_upgrade
from referral import register_referral_handlers
from renewal import renewal_conv_handler, start_renewal
from referral_payout import register_payout_handlers
from util.error_logs import error_handler
import mongo_client

from storage import user_collection, token_collection, payment_collection
from util import restart_recovery as restart_recovery
import util.utils as utils
from storage.notify import (flush_notify_cache_to_db, ensure_notify_records_for_active_users,
                            
                            )
from aiohttp import web
from pwd_loader.gcp_loader import get_secret




logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# --- /restart Callback ---
async def callback_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_restart":
        await query.edit_message_text("♻️ Restarting bot...")
        await restart_recovery.mark_active_users_for_restart()
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

                # Cancel running tasks
                for attr in ["_monitor_task", "_expiry_task", "_reminder_task"]:
                    task = getattr(context.application, attr, None)
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                
                await flush_notify_cache_to_db()
                await asyncio.sleep(1)
                await mongo_client.disconnect()
                await asyncio.sleep(1)
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


# --- /stop Callback ---
async def callback_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_stop":
        await query.edit_message_text("🔌 Shutting down bot...")
        await restart_recovery.mark_active_users_for_restart()

        async def safe_shutdown():
            try:
                # Cancel running tasks
                for attr in ["_monitor_task", "_expiry_task", "_reminder_task"]:
                    task = getattr(context.application, attr, None)
                    if task and not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                
                await context.application.stop()

                # Cancel all other running tasks
                tasks = asyncio.all_tasks()
                for task in tasks:
                    if task is not asyncio.current_task():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                await flush_notify_cache_to_db()
                await asyncio.sleep(1)
                await mongo_client.disconnect()
                await asyncio.sleep(1)
                #await context.application.stop()
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
    await mongo_client.connect()
    await user_collection.load_user_collection_from_mongo()
    await user_collection.ensure_user_indexes()

    await token_collection.load_token_collection_from_mongo()
    await token_collection.create_token_list_index()
    await load_token_data()

    await payment_collection.load_payment_collection_from_mongo()

    await load_admins()
    load_user_tracking()
    # load_user_status()

    load_symbols
    load_tracked_tokens()
    #load_token_history()

    # load_user_tiers()
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
        BotCommand("upgrade", "Upgrade your tier to track more tokens -- /u"),
        BotCommand("renew", "Renew your current tier to continue tracking your tokens -- /rn"),
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

def get_web_app():
    web_app = web.Application()

    async def healthz(request):
        return web.Response(text="OK")

    web_app.router.add_get("/healthz", healthz)
    return web_app

def main():

    BOT_TOKEN = get_secret("bot-token")
    WEBHOOK_PATH = get_secret("webhook-path") or "/webhook"
    PORT = int(os.getenv("PORT", 8080))

    print(f"📦 Starting bot on PORT={PORT}")
    print(f"🌐 Webhook path: {WEBHOOK_PATH}")
    


    # 🚀 Core Launch Commands
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

    app.add_handler(CommandHandler(["addrpc", "ar"], addrpc))
    app.add_handler(CommandHandler(["removerpc", "rr"], removerpc))
    app.add_handler(CommandHandler(["listrpc", "lrp"], listrpc))

    # app.add_handler(CommandHandler("u", start_upgrade))
    # app.add_handler(CommandHandler("r", start_renewal))


    app.add_handler(CallbackQueryHandler(callback_restart, pattern="^confirm_restart$|^cancel_restart$"))
    app.add_handler(CallbackQueryHandler(callback_stop, pattern="^confirm_stop$|^cancel_stop$"))
    app.add_handler(CallbackQueryHandler(callback_reset_confirmation, pattern="^confirm_reset$|^cancel_reset$"))
    app.add_handler(CallbackQueryHandler(handle_removeadmin_callback, pattern="^confirm_removeadmin:|^cancel_removeadmin$"))
    app.add_handler(CallbackQueryHandler(handle_removerpc_callback, pattern="^(confirm_removerpc|cancel_removerpc):"))

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
    #app.run_polling()

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_path=WEBHOOK_PATH,
        web_app=get_web_app()
    )

if __name__ == "__main__":
    main()
