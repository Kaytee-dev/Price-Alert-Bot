# File that handles commands
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from admin import restricted_to_admin, ADMINS
from config import (BASE_URL, SUPER_ADMIN_ID, BOT_NAME,
                    PAGE_SIZE, PAGE_SIZE_ALL, BOT_LOGS_ID,
                    BOT_TG_GROUP, DIVIDER_LINE
                    )

import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
import storage.history as history
import storage.tiers as tiers
import storage.thresholds as thresholds

from monitor import background_price_monitor
from utils import (send_message, refresh_user_commands, load_admins,
                   build_custom_update_from_query, confirm_action)

from upgrade import start_upgrade
from referral import show_referral_page, start_with_referral


# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_with_referral(update, context)


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

    if not users.USER_TRACKING.get(chat_id):
        # User has no tokens tracked yet
        await update.message.reply_text("🔍 You’re not tracking any tokens yet. Use /add <address> to begin.")
        
        # 🚀 Immediately launch dashboard after message
        launch_func = context.bot_data.get("launch_dashboard")
        if launch_func:
            chat_id = update.effective_chat.id

            # 📝 Show 'typing...' animation
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

            await asyncio.sleep(2)
            await launch_func(update, context)
    else:
        # User already tracking tokens
        await update.message.reply_text("🤖 Bot started and monitoring your tokens!")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles stop command, with confirmation only for super admin."""
    chat_id = str(update.effective_chat.id)
    is_super_admin = int(chat_id) == SUPER_ADMIN_ID

    if is_super_admin:
            await confirm_action(
                update,
                context,
                confirm_callback_data="confirm_stop",
                cancel_callback_data="cancel_stop",
                confirm_message="⚠️ Are you sure you want to shut down the bot?"
            )
            return

    # Regular user shutdown (no confirmation needed)
    users.USER_STATUS[chat_id] = False
    users.save_user_status()
    await update.message.reply_text(
        f"🛑 Monitoring paused.\nYou're still tracking {len(users.USER_TRACKING.get(chat_id, []))} token(s). Use /start to resume.")
    

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ... or /a <token_address1>, <token_address2>, ...")
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
            chat_id=BOT_LOGS_ID,
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
        await update.message.reply_text("Usage: /remove <token_address1>, <token_address2>, ... or /rm <token_address1>, <token_address2>, ...")
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
            chat_id=BOT_LOGS_ID,
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
            chat_id=BOT_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )


async def list_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_tokens = users.USER_TRACKING.get(chat_id, [])

    if not user_tokens:
        await update.message.reply_text("📭 You're not tracking any tokens.")
        return

    def has_valid_data(addr):
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        if not history_data:
            return False
        latest = history_data[0]
        return all([
            isinstance(latest.get("marketCap"), (int, float)),
            isinstance(latest.get("priceChange_m5"), (int, float))
        ])

    def get_market_cap(addr):
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        return history_data[0].get("marketCap") if history_data else 0

    sorted_tokens = sorted(
        user_tokens,
        key=lambda addr: (not has_valid_data(addr), -(get_market_cap(addr)))
    )

    context.user_data['tokens_list'] = sorted_tokens
    context.user_data['title'] = "Your Tracked Tokens"
    context.user_data['page_size'] = PAGE_SIZE
    context.user_data['page'] = 0
    await show_token_dashboard(update, context)

async def show_token_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tokens_list = context.user_data.get('tokens_list', [])
    title = context.user_data.get('title', 'Tracked Tokens')
    page = context.user_data.get('page', 0)
    page_size = context.user_data.get('page_size', 5)

    start_idx = page * page_size
    end_idx = start_idx + page_size

    current_tokens = tokens_list[start_idx:end_idx]

    if not current_tokens:
        await update.message.reply_text("📈 No tokens to show on this page.")
        return

    total_pages = (len(tokens_list) - 1) // PAGE_SIZE + 1

    msg = f"\n\n📈 *{title}* (Page {page + 1}/{total_pages})\n\n"

    for addr in current_tokens:
        symbol = symbols.ADDRESS_TO_SYMBOL.get(addr, addr[:6] + "...")
        link = f"[{symbol}]({BASE_URL}{addr})"

        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        if history_data:
            latest = history_data[0]
            market_cap = latest.get("marketCap")
            volume_m5 = latest.get("volume_m5")
            price_change_m5 = latest.get("priceChange_m5")
        else:
            market_cap = volume_m5 = price_change_m5 = None

        mc_text = f"💰 Market Cap: ${market_cap:,.0f}" if market_cap else "💰 Market Cap: Unknown"
        vol_text = f"🔥 5m Volume: ${volume_m5:,.2f}" if volume_m5 else "🔥 5m Volume: Unknown"
        change_text = f"📈 5m Change: {price_change_m5:.2f}%" if price_change_m5 else "📈 5m Change: Unknown"

        msg += (
            f"🪙 {link} ({addr[:6]}...{addr[-4:]})\n"
            f"`{addr}`\n\n"
            f"{mc_text}\n"
            f"{vol_text}\n"
            f"{change_text}\n\n"
            f"{DIVIDER_LINE}\n"
            f"{DIVIDER_LINE}\n\n"
        )

    buttons = []
    nav_buttons = []

    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⏮ Prev", callback_data="list_prev"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page + 1}/{total_pages}", callback_data="noop"))
    if end_idx < len(tokens_list):
        nav_buttons.append(InlineKeyboardButton("Next ⏭", callback_data="list_next"))

    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🏠 Dashboard", callback_data="back_to_dashboard")])

    keyboard = InlineKeyboardMarkup(buttons)

    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=msg,
            reply_markup=keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text(
            text=msg,
            reply_markup=keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )


async def handle_list_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tokens_list = context.user_data.get('tokens_list', [])

    if not tokens_list:
        await query.answer("No tokens to navigate.")
        return

    if query.data == "list_prev":
        context.user_data['page'] = max(0, context.user_data.get('page', 0) - 1)
    elif query.data == "list_next":
        max_page = (len(tokens_list) - 1) // PAGE_SIZE
        context.user_data['page'] = min(max_page, context.user_data.get('page', 0) + 1)

    await show_token_dashboard(update, context)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await confirm_action(
        update,
        context,
        confirm_callback_data="confirm_reset",
        cancel_callback_data="cancel_reset",
        confirm_message="⚠️ Are you sure you want to reset and clear all your tracked tokens?"
    )


async def callback_reset_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_reset":
        await perform_reset(update, context)
    elif query.data == "cancel_reset":
        await query.edit_message_text("❌ Reset canceled.")

async def perform_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            chat_id=BOT_LOGS_ID,
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
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) after /reset."
        logging.info(msg)
        await send_message(
            context.bot,
            msg,
            chat_id=BOT_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

    await update.callback_query.edit_message_text("🔄 Your tracked tokens, symbols, and history have been cleared.")


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
        "/stop — Stop the bot\n",
        "/add or /a — Add a token to track",
        "/remove or /rm — Remove a tracked token\n",
        "/list or /l — List your tracked tokens",
        "/reset or /x — Clear all tracked tokens\n",
        "/help or /h — Show this help menu",
        "/status or /s — View your token tracking stats\n",
        "/threshold or /t — Set your spike alert threshold (%)\n",
    ]

    if is_admin or is_super_admin:
        msg_lines += [
            "\n*🔧 Admin Commands:*",
            "/restart or /rs — Restart the bot",
            "/alltokens or /at — List all tracked tokens\n",
        ]

    if is_super_admin:
        msg_lines += [
            "\n*👑 Super Admin Commands:*",
            "/addadmin or /aa — Add a new admin",
            "/removeadmin or /ra — Remove an admin",
            "/listadmins or /la — List all admins",
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
    
    user_threshold = thresholds.USER_THRESHOLDS.get(chat_id, 5.0)
    user_tier = tiers.get_user_tier(int(chat_id))
    user_limit = tiers.get_user_limit(int(chat_id))

    msg = (
        f"📊 *Bot Status*\n\n"
        f"{monitor_state}\n\n"
        f"🎯 Tier: {user_tier.capitalize()} ({user_limit} token limit)\n"
         f"🔔 Alert threshold: {user_threshold}%\n\n"
        f"👤 You are tracking {len(user_tokens)} token(s).\n"
        f"🌐 Total unique tokens tracked: {len(all_tokens)}\n\n"
        f"💥 Active spikes (≥15%): {spike_count}\n"
        f"🕓 Last update: {last_update if last_update else 'N/A'}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

@restricted_to_admin
async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await confirm_action(
        update,
        context,
        confirm_callback_data="confirm_restart",
        cancel_callback_data="cancel_restart",
        confirm_message="⚠️ Are you sure you want to restart the bot?"
    )

@restricted_to_admin
async def alltokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_tokens = set(addr for tokens_list in users.USER_TRACKING.values() for addr in tokens_list)

    if not all_tokens:
        await update.message.reply_text("📭 No tokens are being tracked by any user.")
        return

    def has_valid_data(addr):
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        if not history_data:
            return False
        latest = history_data[0]
        return all([
            isinstance(latest.get("marketCap"), (int, float)),
            isinstance(latest.get("priceChange_m5"), (int, float))
        ])

    def get_market_cap(addr):
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        return history_data[0].get("marketCap") if history_data else 0

    sorted_tokens = sorted(
        all_tokens,
        key=lambda addr: (not has_valid_data(addr), -(get_market_cap(addr)))
    )

    context.user_data['tokens_list'] = sorted_tokens
    context.user_data['title'] = "All Tracked Tokens"
    context.user_data['page_size'] = PAGE_SIZE_ALL
    context.user_data['page'] = 0
    await show_token_dashboard(update, context)

async def threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("❗ Usage: /threshold <value> or /t <value> (e.g. /threshold 10 or /t 10)")
        return

    try:
        value = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number.")
        return

    thresholds.USER_THRESHOLDS[chat_id] = value
    thresholds.save_user_thresholds()

    await update.message.reply_text(f"✅ Your threshold has been set to {value}%")

async def launch(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.answer()
        target_message = update.callback_query.message
    else:
        target_message = update.message

    if target_message is None:
        logging.warning("❌ No target message found in update.")
        return
    
    chat_id = str(update.effective_chat.id)
    user_id = int(chat_id)

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
    monitor_state = "✅ Monitoring: Active" if is_active else "🔴 Monitoring: Inactive. Start tracking with /start"
    user_tier = tiers.get_user_tier(user_id)
    user_limit = tiers.get_user_limit(user_id)

    # # ✅ Always determine username properly
    # if hasattr(update, "effective_user") and update.effective_user:
    #     user = update.effective_user
    #     username = f"@{user.username}" if user.username else user.full_name
    #     context.user_data["username"] = username  # Save it
    # else:
    #     username = context.user_data.get("username", f"User {chat_id}")

    #username = context.user_data.get("username", f"User {chat_id}")
    username = context.bot_data.get("usernames", {}).get(chat_id, f"User {chat_id}")


    footer_text = (
        f"For providing feedbacks and complaints, join our telegram group\n[👉 --here--]({BOT_TG_GROUP})"
    )
    msg = (
        f"👋 Hey *{username}*, welcome to *{BOT_NAME}*!\n\n"
        f"Tracks tokens that cooled off but still have holders. Alerts you when they’re warming up for Round 2. 🔥📈\n\n"
        f"{monitor_state}\n"
        f"🎯 Tier: {user_tier.capitalize()} ({user_limit} token limit)\n\n"
        f"👤 You are tracking {len(user_tokens)} token(s).\n"
        f"🌐 Total unique tokens tracked: {len(all_tokens)}\n\n"
        f"💥 Active spikes (≥15%): {spike_count}\n"
        f"🕓 Last update: {last_update if last_update else 'N/A'}\n\n\n"
        f"{DIVIDER_LINE}\n"
        f"{footer_text}\n"
        f"{DIVIDER_LINE}"
    )


    keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("✅ Start Tracking", callback_data="cmd_start"),
        InlineKeyboardButton("🛑 Stop Tracking", callback_data="cmd_stop")
    ],
    [
        InlineKeyboardButton("🔄 Reset List", callback_data="cmd_reset"),
        InlineKeyboardButton("📋 List Tokens", callback_data="cmd_list")
    ],
    [
        InlineKeyboardButton("👤 Refferral", callback_data="cmd_refer"),
    ],
    [
        InlineKeyboardButton("📊 Tracking Status", callback_data="cmd_status"),
        InlineKeyboardButton("❓ Help", callback_data="cmd_help")
    ],
    [
        InlineKeyboardButton("⭐ Upgrade", callback_data="cmd_upgrade")
    ],
    ])

    #await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    await target_message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=keyboard)


async def handle_dashboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Answer the callback query
    
    callback_data = query.data
    chat_id = str(query.message.chat_id)
    user_id = int(chat_id)
    
    # Handle upgrade button by transferring to the conversation
    if callback_data == "cmd_upgrade":
        # This will redirect to the ConversationHandler
        return await start_upgrade(update, context)

    custom_update = build_custom_update_from_query(query)

    
    # Call the appropriate function based on the callback data
    if callback_data == "cmd_start":
        await start(custom_update, context)
    elif callback_data == "cmd_stop":
        await stop(custom_update, context)
    elif callback_data == "cmd_reset":
        await reset(custom_update, context)
    elif callback_data == "cmd_list":
        await list_tokens(custom_update, context)
    elif callback_data == "cmd_status":
        await status(custom_update, context)
    elif callback_data == "cmd_help":
        await help_command(custom_update, context)
    elif callback_data == "cmd_refer":
        await show_referral_page(custom_update, context)

