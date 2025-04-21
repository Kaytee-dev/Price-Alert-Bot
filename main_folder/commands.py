# File that handles commands
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes

from admin import restricted_to_admin, ADMINS
from config import BASE_URL, SUPER_ADMIN_ID

import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
import storage.history as history
import storage.tiers as tiers

from monitor import background_price_monitor
from utils import send_message, refresh_user_commands, load_admins


# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = int(chat_id)
    is_admin = user_id in ADMINS

    users.USER_STATUS[chat_id] = True
    users.save_user_status()


     # Start global monitor loop if not already running (admin OR first-time user)
    if not getattr(context.application, "_monitor_started", False):
        logging.info("📡 Monitor loop will be called...")

        # Create the task and store the reference
        monitor_task = context.application.create_task(background_price_monitor(context.application))
        logging.info("📡 Monitor loop was called successfully...")

        context.application._monitor_task = monitor_task  # Store reference to the task
        context.application._monitor_started = True
        logging.info(f"🟢 Monitor loop started by {'admin' if is_admin else 'user'} {chat_id}")
    
    await refresh_user_commands(user_id, context.bot)

    await update.message.reply_text("🤖 Bot started and monitoring your tokens!")

    if not users.USER_TRACKING.get(chat_id):
        await update.message.reply_text("🔍 You’re not tracking any tokens yet. Use /add <address> to begin.")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles stop command, with confirmation only for super admin."""
    chat_id = str(update.effective_chat.id)
    is_super_admin = int(chat_id) == SUPER_ADMIN_ID

    if is_super_admin:
        # Send confirmation prompt before stopping for admin
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Shutdown", callback_data="confirm_stop")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_stop")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "⚠️ Are you sure you want to shut down the bot?",
            reply_markup=reply_markup
        )
        return  # Don't proceed further until admin confirms

    # Regular user shutdown (no confirmation needed)
    users.USER_STATUS[chat_id] = False
    users.save_user_status()
    await update.message.reply_text(
        f"🛑 Monitoring paused.\nYou're still tracking {len(users.USER_TRACKING.get(chat_id, []))} token(s). Use /start to resume.")
    

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return

    # Checking if user exists first
    if chat_id not in users.USER_TRACKING:
        users.USER_TRACKING[chat_id] = []

    # Getting user tokens and current tier to calculate limit 
    # before adding new ones

    # Get tier and enforce super admin status
    await tiers.enforce_token_limit(int(chat_id), bot=context.bot)
    
    current_tokens = users.USER_TRACKING[chat_id]
    tier_limit = tiers.get_user_limit(chat_id)
    already_tracking = len(current_tokens)
    available_slots = tier_limit - already_tracking

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return
    
    already_present = [addr for addr in addresses if addr in current_tokens]
    tokens_to_add = [addr for addr in addresses if addr not in current_tokens]
    tokens_allowed = tokens_to_add[:available_slots]
    tokens_dropped = tokens_to_add[available_slots:]


    for address in tokens_allowed:
        users.USER_TRACKING[chat_id].append(address)
        if address not in tokens.TRACKED_TOKENS:
            tokens.TRACKED_TOKENS.append(address)
    
    users.save_user_tracking()
    tokens.save_tracked_tokens()

    # Auto-start the user if they haven't started yet
    if users.USER_STATUS.get(chat_id, False) is False:
        users.USER_STATUS[chat_id] = True  # Mark as started
        
        # Log and notify the super admin
        logging.info(f"🤖 User {chat_id} auto-started monitoring.")
        await send_message(
            context.bot,
            f"🧹 User {chat_id} auto-started monitoring.",
            chat_id=SUPER_ADMIN_ID,
            super_admin=SUPER_ADMIN_ID
        )

        # Trigger the /start functionality for the user
        await start(update, context)  # Directly call the /start function logic


    if tokens_allowed:
        await update.message.reply_text(f"✅ Tracking token(s):\n" + "\n".join(tokens_allowed))
    
    if already_present:
        await update.message.reply_text(f"ℹ️ Already tracking:\n" + "\n".join(already_present))

    if tokens_dropped:
        await update.message.reply_text(
            f"🚫 Limit Reached! You can only track {tier_limit} tokens.\n"
            f"The following were not added:\n" + "\n".join(tokens_dropped)
        )

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ...")
        return

    if chat_id not in users.USER_TRACKING:
        await update.message.reply_text("ℹ️ You're not tracking any tokens.")
        return

    removed = []
    not_found = []
    tokens_removed = []

    for address in addresses:
        if address in users.USER_TRACKING[chat_id]:
            users.USER_TRACKING[chat_id].remove(address)
            removed.append(address)
        else:
            not_found.append(address)

    # Clean up global tracked list
    for token in removed:
        if not any(token in tokens_list for tokens_list in users.USER_TRACKING.values()):
            if token in tokens.TRACKED_TOKENS:
                tokens.TRACKED_TOKENS.remove(token)
                tokens_removed.append(token)
                symbols.ADDRESS_TO_SYMBOL.pop(token, None)
                history.TOKEN_DATA_HISTORY.pop(token, None)
                history.LAST_SAVED_HASHES.pop(token, None)

    users.save_user_tracking()
    tokens.save_tracked_tokens()
    symbols.save_symbols_to_file()

    if removed:
        await update.message.reply_text(f"🗑️ Removed token(s):\n" + "\n".join(removed))
    if not_found:
        await update.message.reply_text(f"❌ Address(es) not found in your tracking list:\n" + "\n".join(not_found))
    if tokens_removed:
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) from tracking after /remove."
        logging.info(msg)
        await send_message(
            context.bot,
            msg,
            chat_id=SUPER_ADMIN_ID,
            super_admin=SUPER_ADMIN_ID
        )
    
    # If user no longer tracks any tokens, clean up their entry
    if not users.USER_TRACKING.get(chat_id):
        users.USER_TRACKING.pop(chat_id, None)
        users.USER_STATUS.pop(chat_id, None)
        users.save_user_tracking()
        users.save_user_status()
        logging.info(f"🧹 Removed user {chat_id} from tracking (no tokens left).")
        await send_message(
            context.bot,
            f"🧹 Removed user {chat_id} from tracking (no tokens left).",
            chat_id=SUPER_ADMIN_ID,
            super_admin=SUPER_ADMIN_ID
        )


async def list_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    user_tokens = users.USER_TRACKING.get(chat_id, [])
    if not user_tokens:
        await update.message.reply_text("📭 You're not tracking any tokens.")
        return

    msg = "📊 Your Tracked Tokens:\n"

    for addr in user_tokens:
        symbol = symbols.ADDRESS_TO_SYMBOL.get(addr, addr[:6] + "...")
        link = f"[{symbol}]({BASE_URL}{addr})"

        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        market_cap = history_data[0].get("marketCap") if history_data else None
        mc_text = f" - Market Cap: ${market_cap:,.0f}" if market_cap else ""

        msg += f"- {link} ({addr[:6]}...{addr[-4:]}){mc_text}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    # Step 1: Deactivate user if they were active
    if users.USER_STATUS.get(chat_id):
        users.USER_STATUS[chat_id] = False
        users.save_user_status()
        logging.info(f"🔴 Deactivated monitoring for user {chat_id}")


    tokens_removed = []

    user_tokens = users.USER_TRACKING.get(chat_id, [])

    # removing chat id of users who invoked /reset command but saved users tokens
    if chat_id in users.USER_TRACKING:
        users.USER_TRACKING.pop(chat_id, None)
        logging.info(f"🧹 Removed user {chat_id} from tracking.")
        await send_message(
            context.bot,
            f"🧹 Removed user {chat_id} from tracking.",
            chat_id=SUPER_ADMIN_ID,
            super_admin=SUPER_ADMIN_ID
        )


    # Clean tracked tokens that are no longer used
    for token in user_tokens:
        if not any(token in tokens_list for tokens_list in users.USER_TRACKING.values()):
            if token in tokens.TRACKED_TOKENS:
                tokens.TRACKED_TOKENS.remove(token)
                tokens_removed.append(token)
                symbols.ADDRESS_TO_SYMBOL.pop(token, None)
                history.TOKEN_DATA_HISTORY.pop(token, None)
                history.LAST_SAVED_HASHES.pop(token, None)

    users.save_user_tracking()
    tokens.save_tracked_tokens()
    symbols.save_symbols_to_file()

    if tokens_removed:
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) from tracking after /reset."
        logging.info(msg)
        await send_message(
            context.bot,
            msg,
            chat_id=SUPER_ADMIN_ID,
            super_admin=SUPER_ADMIN_ID
        )
        
    await update.message.reply_text("🔄 Your tracked tokens, symbols, and history have been cleared.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = int(chat_id)

    admin = load_admins()
    is_admin = user_id in admin
    is_super_admin = user_id == SUPER_ADMIN_ID

    msg_lines = [

        "*🤖 Price Alert Bot Help*\n",
        "Use the following commands to manage your token alerts:\n",
        "*🔹 Regular Commands:*",
        "/start — Start the bot",
        "/stop — Stop the bot",
        "/add — Add a token to track",
        "/remove — Remove a tracked token",
        "/list — List your tracked tokens",
        "/reset — Clear all tracked tokens",
        "/help — Show this help menu",
        "/status — View your token tracking stats\n",
    ]

    if is_admin or is_super_admin:
        msg_lines += [
            "\n*🔧 Admin Commands:*",
            "/restart — Restart the bot",
            "/alltokens — List all tracked tokens\n",
        ]

    if is_super_admin:
        msg_lines += [
            "\n*👑 Super Admin Commands:*",
            "/addadmin — Add a new admin",
            "/removeadmin — Remove an admin",
            "/listadmins — List all admins",
        ]

    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown"
    )
    

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_tokens = users.USER_TRACKING.get(chat_id, [])
    all_tokens = set(addr for tokens_list in users.USER_TRACKING.values() for addr in tokens_list)

    spike_count = 0
    for addr in all_tokens:
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        if history_data and isinstance(history_data[0].get("priceChange_m5"), (int, float)):
            if history_data[0]["priceChange_m5"] >= 15:
                spike_count += 1

    last_update = None
    timestamps = [entry[0].get("timestamp") for entry in history.TOKEN_DATA_HISTORY.values() if entry]
    if timestamps:
        last_update = max(timestamps)

    is_active = users.USER_STATUS.get(chat_id, False)
    monitor_state = "✅ Monitoring: Active" if is_active else "🔴 Monitoring: Inactive"

    user_tier = tiers.get_user_tier(int(chat_id))
    user_limit = tiers.get_user_limit(int(chat_id))

    msg = (
        f"📊 *Bot Status*\n\n"
        f"{monitor_state}\n"
        f"🎯 Tier: {user_tier.capitalize()} ({user_limit} token limit)\n"
        f"👤 You are tracking {len(user_tokens)} token(s).\n"
        f"🌐 Total unique tokens tracked: {len(all_tokens)}\n"
        f"💥 Active spikes (≥15%): {spike_count}\n"
        f"🕓 Last update: {last_update if last_update else 'N/A'}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

@restricted_to_admin
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Restart", callback_data="confirm_restart")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_restart")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("⚠️ Are you sure you want to restart the bot?", reply_markup=reply_markup)


@restricted_to_admin
async def alltokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_tokens = set(addr for tokens_list in users.USER_TRACKING.values() for addr in tokens_list)
    if not all_tokens:
        await update.message.reply_text("📭 No tokens are being tracked by any user.")
        return

    def get_market_cap(addr):
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        return history_data[0].get("marketCap") if history_data else None

    sorted_tokens = sorted(all_tokens, key=lambda addr: (get_market_cap(addr) is None, -(get_market_cap(addr) or 0)))

    msg = f"📦 *All Tracked Tokens (Total: {len(all_tokens)}):*\n\n"
    for addr in sorted_tokens:
        symbol = symbols.ADDRESS_TO_SYMBOL.get(addr, addr[:6] + "...")
        link = f"[{symbol}]({BASE_URL}{addr})"
        market_cap = get_market_cap(addr)
        mc_text = f" - Market Cap: ${market_cap:,.0f}" if market_cap else ""
        msg += f"- {link} ({addr[:6]}...{addr[-4:]}){mc_text}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")