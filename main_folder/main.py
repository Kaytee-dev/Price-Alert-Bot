# token_alert_bot.py

import asyncio
import logging
import os
import sys

from telegram import Update, BotCommand, BotCommandScopeDefault
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes,
)

from config import (
    BOT_TOKEN, RESTART_FLAG_FILE, ACTIVE_RESTART_USERS_FILE, SUPER_ADMIN_ID
)

from commands import (
    start, stop, add, remove, list_tokens, reset, help_command, 
    status, restart, alltokens, threshold, handle_dashboard_button, launch
)

import storage.tokens
import storage.users
from storage.tiers import load_user_tiers
import storage.tiers as tiers
import storage.thresholds as thresholds

from storage.tokens import load_tracked_tokens, save_tracked_tokens, load_active_token_data
from storage.symbols import load_symbols_from_file
from storage.users import load_user_tracking, load_user_status, save_user_status
from storage.history import load_token_history
from storage.thresholds import load_user_thresholds, save_user_thresholds

from admin import (
    addadmin, removeadmin, listadmins,
    handle_removeadmin_callback, load_admins, ADMINS
)
from utils import load_json, save_json, send_message, refresh_user_commands
from monitor import background_price_monitor


logging.basicConfig(level=logging.INFO)


async def callback_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_restart":
        await query.edit_message_text("♻️ Restarting bot...")
        admin_id = query.from_user.id

        async def safe_restart():
            try:
                if not getattr(context.application, "_monitor_started", False):
                    logging.info("ℹ️ Monitor was never started — skipping restart logic.")
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
                        logging.info("ℹ️ Monitor task exists but already completed.")
                else:
                    logging.warning("⚠️ Monitor task reference missing despite start flag — possible inconsistency.")

                await context.application.stop()
                await asyncio.sleep(1)

                logging.info("🔁 Restarting...")
            except Exception as e:
                logging.error(f"Restart error: {e}")
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
                logging.info("🔌 Bot stopped cleanly.")
            except Exception as e:
                logging.error(f"Shutdown error: {e}")
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
        logging.info("🔄 Monitor loop auto-started after restart recovery.")

    # 🔧 Set fallback default commands
    default_cmds = [
        BotCommand("launch", "Launch bot dashboard"),
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

def main():

    load_admins()
    load_user_tracking()
    load_user_status()

    load_symbols_from_file()
    
    load_tracked_tokens()
    load_token_history()
    load_active_token_data()
    load_user_tiers()

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
            logging.info("🧹 Cleaned up restart state files.")
        except Exception as e:
            logging.warning(f"⚠️ Failed to clean restart state files: {e}")

    # Rebuild from loaded data
    all_tokens = set()
    for token_list in storage.users.USER_TRACKING.values():
        all_tokens.update(token_list)
    storage.tokens.TRACKED_TOKENS = sorted(all_tokens)
    storage.tokens.save_tracked_tokens()
    logging.info(f"🔁 Rebuilt tracked tokens list: {len(storage.tokens.TRACKED_TOKENS)} tokens.")

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

    app.add_handler(CommandHandler("launch", launch))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))

    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("a", add))

    app.add_handler(CommandHandler("alltokens", alltokens))
    app.add_handler(CommandHandler("at", alltokens))

    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("rm", remove))

    app.add_handler(CommandHandler("list", list_tokens))
    app.add_handler(CommandHandler("l", list_tokens))

    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("x", reset))

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("h", help_command))

    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("rs", restart))

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("s", status))

    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("aa", addadmin))

    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("ra", removeadmin))

    app.add_handler(CommandHandler("listadmins", listadmins))
    app.add_handler(CommandHandler("la", listadmins))

    app.add_handler(CommandHandler("threshold", threshold))
    app.add_handler(CommandHandler("t", threshold))

    app.add_handler(CallbackQueryHandler(callback_restart, pattern="^confirm_restart$|^cancel_restart$"))
    app.add_handler(CallbackQueryHandler(callback_stop, pattern="^confirm_stop$|^cancel_stop$"))
    app.add_handler(CallbackQueryHandler(handle_removeadmin_callback, pattern="^confirm_removeadmin:|^cancel_removeadmin$"))
    app.add_handler(CallbackQueryHandler(handle_dashboard_button, pattern="^cmd_"))



    app.run_polling()



if __name__ == "__main__":
    main()
