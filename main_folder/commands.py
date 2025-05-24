# File that handles commands
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from admin import restricted_to_admin, ADMINS
from config import (BASE_URL, SUPER_ADMIN_ID, BOT_NAME,
                    PAGE_SIZE, PAGE_SIZE_ALL,
                    BOT_TG_GROUP, DIVIDER_LINE, BOT_INFO_LOGS_ID
                    )

import storage.users as users
import storage.tokens as tokens
import storage.symbols as symbols
import storage.history as history
import storage.tiers as tiers
import storage.thresholds as thresholds

from monitor import background_price_monitor
from util.utils import (send_message, refresh_user_commands, load_admins,
                   build_custom_update_from_query, confirm_action)

from upgrade import start_upgrade
from referral import show_referral_page, start_with_referral
from renewal import start_renewal
from datetime import datetime
import api
from util.get_all_tracked_tokens_util import get_all_tracked_tokens

logger = logging.getLogger(__name__)

# --- Telegram Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_with_referral(update, context)


    user_id = update.effective_chat.id
    chat_id = str(user_id)
    is_admin = user_id in ADMINS

    users.USER_STATUS[chat_id] = True
    users.save_user_status()


     # Start global monitor loop if not already running (admin OR first-time user)
    if not getattr(context.application, "_monitor_started", False):
        logger.info("📡 Monitor loop will be called...")

        # Create the task and store the reference
        monitor_task = context.application.create_task(background_price_monitor(context.application))
        logger.info("📡 Monitor loop was called successfully...")

        context.application._monitor_task = monitor_task  # Store reference to the task
        context.application._monitor_started = True
        logger.info(f"🟢 Monitor loop started by {'admin' if is_admin else 'user'} {chat_id}")
    
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
    users.save_user_status(chat_id)
    await update.message.reply_text(
        f"🛑 Monitoring paused.\nYou're still tracking {len(users.USER_TRACKING.get(chat_id, []))} token(s). Use /start to resume.")
    

# Updated display format for grouped token additions by chain
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    chat_id = str(user_id)

    if not context.args:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ... or /a <token_address1>, <token_address2>, ...")
        return

    if chat_id not in users.USER_TRACKING:
        users.USER_TRACKING[chat_id] = {}

    await tiers.enforce_token_limit(int(chat_id), bot=context.bot)

    user_chains = users.USER_TRACKING[chat_id]
    tier_limit = tiers.get_user_limit(chat_id)
    already_tracking = sum(len(tokens) for tokens in user_chains.values())
    available_slots = tier_limit - already_tracking

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("Usage: /add <token_address1>, <token_address2>, ...")
        return

    status_message = await update.message.reply_text("🔍 Looking up token information...")

    tokens_added = {}
    tokens_already_tracking = []
    tokens_failed = []
    tokens_dropped = []
    slots_used = 0

    for address in addresses:
        await status_message.edit_text(f"🔍 Looking up token information for {address}...")

        try:
            #token_info = await asyncio.to_thread(api.get_token_chain_info, address)
            token_info = await api.get_token_chain_info(address)

            if not token_info or not token_info.get('chain_id'):
                tokens_failed.append(address)
                continue

            chain_id = token_info['chain_id']
            symbol = token_info.get('symbol', address[:6])

            if chain_id not in user_chains:
                user_chains[chain_id] = []

            if address in user_chains[chain_id]:
                tokens_already_tracking.append(f"{chain_id}:{address}")
                continue

            if slots_used >= available_slots:
                tokens_dropped.append(address)
                continue

            user_chains[chain_id].append(address)

            if chain_id not in tokens.TRACKED_TOKENS:
                tokens.TRACKED_TOKENS[chain_id] = []

            if address not in tokens.TRACKED_TOKENS[chain_id]:
                tokens.TRACKED_TOKENS[chain_id].append(address)

            symbols.ADDRESS_TO_SYMBOL[address] = symbol

            if chain_id not in tokens_added:
                tokens_added[chain_id] = []
            tokens_added[chain_id].append((address, symbol))

            slots_used += 1

        except Exception as e:
            logger.error(f"Error adding token {address}: {str(e)}")
            tokens_failed.append(address)

    users.save_user_tracking()
    tokens.save_tracked_tokens()
    symbols.save_symbols_to_file()

    response_parts = []
    if tokens_added:
        total = sum(len(lst) for lst in tokens_added.values())
        response_parts.append(f"✅ Tracking {total} new token(s):")
        for chain_id, token_list in tokens_added.items():
            response_parts.append(f"\n🌐 {chain_id.upper()}")
            for addr, sym in token_list:
                response_parts.append(f"- {addr} ({sym})")

    if tokens_already_tracking:
        response_parts.append(f"\nℹ️ Already tracking {len(tokens_already_tracking)} token(s):\n" + "\n".join(tokens_already_tracking))
    if tokens_failed:
        response_parts.append(f"\n❌ Failed to add {len(tokens_failed)} token(s):\n" + "\n".join(tokens_failed))
    if tokens_dropped:
        response_parts.append(
            f"\n🚫 Limit Reached! You can only track {tier_limit} tokens.\n"
            f"The following were not added ({len(tokens_dropped)}):\n" + "\n".join(tokens_dropped)
        )

    await status_message.edit_text("\n".join(response_parts))

    if tokens_added and users.USER_STATUS.get(chat_id, False) is False:
        users.USER_STATUS[chat_id] = True
        user_chat = await context.bot.get_chat(user_id)
        user_name = user_chat.full_name or f"User {user_id}"

        logger.info(f"🤖 {user_name} auto-started monitoring.")
        await send_message(
            context.bot,
            f"🧹 {user_name} auto-started monitoring.",
            chat_id=BOT_INFO_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

        await start(update, context)


# Updated `remove` command for new USER_TRACKING structure
async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    chat_id = str(user_id)

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

    user_chains = users.USER_TRACKING[chat_id]
    removed = []
    not_found = []
    tokens_removed = []

    for address in addresses:
        found = False
        for chain_id, addr_list in user_chains.items():
            if address in addr_list:
                addr_list.remove(address)
                removed.append(address)
                found = True
                break
        if not found:
            not_found.append(address)

    # Clean up empty chain entries
    users.USER_TRACKING[chat_id] = {
        k: v for k, v in user_chains.items() if v
    }

    # Clean up global tracked list
    for address in removed:
        still_used = any(
            address in chain_list
            for user_tokens in users.USER_TRACKING.values()
            for chain_list in user_tokens.values()
        )
        if not still_used:
            for chain_id, addr_list in tokens.TRACKED_TOKENS.items():
                if address in addr_list:
                    addr_list.remove(address)
                    tokens_removed.append(address)
            symbols.ADDRESS_TO_SYMBOL.pop(address, None)
            history.TOKEN_DATA_HISTORY.pop(address, None)
            history.LAST_SAVED_HASHES.pop(address, None)

    users.save_user_tracking()
    tokens.save_tracked_tokens()
    symbols.save_symbols_to_file()

    if removed:
        await update.message.reply_text(f"🗑️ Removed token(s):\n" + "\n".join(removed))
    if not_found:
        await update.message.reply_text(f"❌ Address(es) not found in your tracking list:\n" + "\n".join(not_found))
    if tokens_removed:
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) from tracking after /remove."
        logger.info(msg)
        await send_message(
            context.bot,
            msg,
            chat_id=BOT_INFO_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

    if not users.USER_TRACKING.get(chat_id):
        users.USER_TRACKING.pop(chat_id, None)
        users.USER_STATUS.pop(chat_id, None)
        users.save_user_tracking()
        users.save_user_status()

        user_chat = await context.bot.get_chat(user_id)
        user_name = user_chat.full_name or f"User {user_id}"

        logger.info(f"🧹 Removed {user_name} from tracking (no tokens left).")
        await send_message(
            context.bot,
            f"🧹 Removed {user_name} from tracking (no tokens left).",
            chat_id=BOT_INFO_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )


# Updated `list_tokens` to support new USER_TRACKING structure
async def list_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = str(update.effective_chat.id)
    user_tokens = get_all_tracked_tokens(chat_id)
    
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
    buttons.append([InlineKeyboardButton("🏠 Back to Dashboard", callback_data="back_to_dashboard")])

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

    if query.data == "back_to_dashboard":
        await query.answer()
        # Delete the current message containing the token list
        await query.message.delete()
        # Directly call the launch function after deletion
        await launch(update, context)
        return

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
        # Check if we came from dashboard and need to add back button
        if context.user_data.get('from_dashboard', False):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Back to Dashboard", callback_data="go_to_dashboard")
            ]])
            await query.edit_message_text("❌ Reset canceled.", reply_markup=keyboard)
            # Reset the flag
            context.user_data['from_dashboard'] = False
        else:
            await query.edit_message_text("❌ Reset canceled.")

        #await query.edit_message_text("❌ Reset canceled.")

# Updated `perform_reset` for chain-aware USER_TRACKING structure
async def perform_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    chat_id = str(user_id)

    if users.USER_STATUS.get(chat_id):
        users.USER_STATUS[chat_id] = False
        users.save_user_status()
        logger.info(f"🔴 Deactivated monitoring for user {chat_id}")

    user_chains = users.USER_TRACKING.get(chat_id, {})
    tokens_removed = []

    # Remove user entry
    if chat_id in users.USER_TRACKING:
        users.USER_TRACKING.pop(chat_id, None)

        user_chat = await context.bot.get_chat(user_id)
        user_name = user_chat.full_name or f"User {user_id}"

        logger.info(f"🧹 Removed {user_name} from tracking.")
        await send_message(
            context.bot,
            f"🧹 Removed {user_name} (ID: {user_id}) from tracking.",
            chat_id=BOT_INFO_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

    # Clean up unreferenced tokens
    for chain_tokens in user_chains.values():
        for token in chain_tokens:
            still_used = any(
                token in chain_list
                for user_tokens in users.USER_TRACKING.values()
                for chain_list in user_tokens.values()
            )
            if not still_used:
                for chain_id, addr_list in tokens.TRACKED_TOKENS.items():
                    if token in addr_list:
                        addr_list.remove(token)
                        tokens_removed.append(token)
                symbols.ADDRESS_TO_SYMBOL.pop(token, None)
                history.TOKEN_DATA_HISTORY.pop(token, None)
                history.LAST_SAVED_HASHES.pop(token, None)

    users.save_user_tracking()
    tokens.save_tracked_tokens()
    symbols.save_symbols_to_file()

    if tokens_removed:
        msg = f"🧼 Removed {len(tokens_removed)} untracked token(s) after /reset."
        logger.info(msg)
        await send_message(
            context.bot,
            msg,
            chat_id=BOT_INFO_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

    await update.callback_query.edit_message_text("🔄 Your tracked tokens, symbols, and history have been cleared.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id

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
            "/checkpayment or /cp — Retrieve user payment log",
            "/manualupgrade or /mu — Manually upgrade user tier",
            "/listrefs or /lr — View user referral data\n",

        ]

    if is_super_admin:
        msg_lines += [
            "\n*👑 Super Admin Commands:*",
            "/addadmin or /aa — Add a new admin",
            "/removeadmin or /ra — Remove an admin\n",
            "/listadmins or /la — List all admins",
            "/listwallet or /lw — List all wallets\n",
            "/addwallet or /aw — Add regular wallets",
            "/removewallet or /rw — Remove regular wallets\n",
            "/addpayout or /ap — Add payout wallets",
            "/removepayout or /rp — Remove payout wallets",
        ]


    msg_txt = "\n".join(msg_lines)

    # await update.message.reply_text(
    #     "\n".join(msg_lines),
    #     parse_mode="Markdown"
    # )

    # Check if we came from dashboard and need to add back button
    if context.user_data.get('from_dashboard', False):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Back to Dashboard", callback_data="go_to_dashboard")
        ]])
        await update.message.reply_text(msg_txt, parse_mode="Markdown", reply_markup=keyboard)
        # Reset the flag
        context.user_data['from_dashboard'] = False
    else:
        await update.message.reply_text(msg_txt, parse_mode="Markdown")


    
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    chat_id = str(user_id)
    user_tokens = get_all_tracked_tokens(user_id)
    
    all_tokens = set(
        addr
        for user_data in users.USER_TRACKING.values()
        for chain_tokens in user_data.values()
        for addr in chain_tokens
    )

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

    if context.user_data.get('from_dashboard', False):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Back to Dashboard", callback_data="go_to_dashboard")
        ]])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        context.user_data['from_dashboard'] = False
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

    
    #await update.message.reply_text(msg, parse_mode="Markdown")

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
    all_tokens = set(
        addr
        for user_chains in users.USER_TRACKING.values()
        for chain_tokens in user_chains.values()
        for addr in chain_tokens
    )

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
        logger.warning("❌ No target message found in update.")
        return
    
    user_id = update.effective_chat.id
    chat_id = str(user_id)

    user_chains = users.USER_TRACKING.get(chat_id, {})
    user_tokens = [addr for chain_tokens in user_chains.values() for addr in chain_tokens]

    all_tokens = set(
        addr
        for user_data in users.USER_TRACKING.values()
        for chain_tokens in user_data.values()
        for addr in chain_tokens
    )
    
    spike_count = 0

    for addr in all_tokens:
        history_data = history.TOKEN_DATA_HISTORY.get(addr, [])
        if history_data and isinstance(history_data[0].get("priceChange_m5"), (int, float)):
            if history_data[0]["priceChange_m5"] >= 5:
                spike_count += 1

    last_update = None
    timestamps = [entry[0].get("timestamp") for entry in history.TOKEN_DATA_HISTORY.values() if entry]
    if timestamps:
        last_update = max(timestamps)

    is_active = users.USER_STATUS.get(chat_id, False)
    monitor_state = "✅ Monitoring: Active" if is_active else "🔴 Monitoring: Inactive. Start tracking with /start"
    user_tier = tiers.get_user_tier(user_id)
    user_limit = tiers.get_user_limit(user_id)

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
        f"💥 Active spikes (≥5%): {spike_count}\n"
    )

    # Add expiry info
    expiry_date = tiers.get_user_expiry(user_id)

    
    if expiry_date:
        days_left = (expiry_date - datetime.now()).days
        grace_period = 3
        grace_period_remaining = grace_period + days_left

        if days_left in range(1,8):
            msg += f"\n⏰ Your {user_tier.capitalize()} tier expires in *{days_left} days*\n"

        elif days_left <= 0:
            msg += f"\n⚠️ Your {user_tier.capitalize()} tier has expired! "\
                        f"You have {grace_period_remaining}/{grace_period} days before your tier is downgraded. "\
                            f"Use /renew to renew your tier to avoid disruptions.\n\n"

    
    msg += (
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
        InlineKeyboardButton("📊 Tracking Status", callback_data="cmd_status"),
        InlineKeyboardButton("❓ Help", callback_data="cmd_help")
    ],
    [
        InlineKeyboardButton("⭐ Upgrade", callback_data="cmd_upgrade")
    ],
    [
        InlineKeyboardButton("👤 Refferral", callback_data="cmd_refer"),
        InlineKeyboardButton("🔄 Renew Tier", callback_data="cmd_renew")
    ],
    ])

    await target_message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=keyboard)


async def handle_dashboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Answer the callback query
    
    callback_data = query.data
    chat_id = str(query.message.chat_id)
    user_id = int(chat_id)

     # Set flag to indicate that we're coming from dashboard
    context.user_data['from_dashboard'] = True
    
    # Handle upgrade button by transferring to the conversation
    if callback_data == "cmd_upgrade":
        # This will redirect to the ConversationHandler
        return await start_upgrade(update, context)
    elif callback_data == "cmd_renew":
        # This will redirect to the renewal ConversationHandler
        return await start_renewal(update, context)
    

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


async def back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Delete the current message
    await query.message.delete()
    # Call the launch function to show the dashboard
    await launch(update, context)