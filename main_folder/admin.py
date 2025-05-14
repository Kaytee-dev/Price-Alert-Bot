from typing import Callable
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler, MessageHandler,
                          filters, CallbackQueryHandler
                          )
from util.utils import load_json, save_json, refresh_user_commands, confirm_action
from config import (ADMINS_FILE, SUPER_ADMIN_ID, WALLET_SECRETS_FILE, SOLSCAN_BASE, SOLANA_RPC,
                    TOKEN_PROGRAM_ID, SYSTEM_PROGRAM_ID, LIST_WALLET_PAGE, WALLET_PAGE_SIZE,
                    PAYOUT_WALLETS_FILE
                    )

import storage.tiers as tiers
import storage.payout as payout
import referral

from base58 import b58decode
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.api import Client

from pwd_loader.env_loader import get_wallet_password
from secrets_key import encrypt_key
from storage.payout import add_wallet_to_payout_list
import secrets_key as secrets_key
import util.wallet_sync as wallet_sync
import util.manual_upgrade as manual_upgrade
import storage.payment_logs as payment_logs

import json
import os
import requests

# Manual upgrade conversation states
MANUAL_USER_ID, MANUAL_TX_SIG, MANUAL_PAYMENT_ID = range(3)

# User payment log query conversation states 
ASK_USER_ID, ASK_PAYMENT_ID = range(2)
ADMINS = set()

SOLANA_CLIENT = Client(SOLANA_RPC)

# --- Super Admin ID ---
#SUPER_ADMIN_ID = -4710110042  # Replace this with your actual ID

# --- Load/Save Admins ---
def load_admins():
    global ADMINS
    ADMINS = set(load_json(ADMINS_FILE, [], "admins"))
    ADMINS.add(SUPER_ADMIN_ID)  # ensure super admin is always present

def save_admins():
    save_json(ADMINS_FILE, list(ADMINS), "admins")

# --- Admin Decorators ---
def restricted_to_admin(func: Callable):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in ADMINS:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context)
    return wrapper

def restricted_to_super_admin(func: Callable):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != SUPER_ADMIN_ID:
            await update.message.reply_text("❌ Only the super admin can perform this action.")
            return
        return await func(update, context)
    return wrapper

# --- Admin Commands ---
@restricted_to_super_admin
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id or @username>")
        return

    arg = context.args[0]
    try:
        if arg.startswith("@"):  # username
            user = await context.bot.get_chat(arg)
        else:
            user_id = int(arg)
            user = await context.bot.get_chat(user_id)

        if not user or user.type != 'private':
            raise ValueError("Not a valid user.")

        user_id = user.id
    except Exception:
        await update.message.reply_text("❌ Invalid Telegram user ID or username.")
        return

    if user_id in ADMINS:
        await tiers.promote_to_premium(user_id, bot=context.bot)
        await refresh_user_commands(user_id, bot=context.bot)
        await update.message.reply_text(f"ℹ️ User {user_id} is already an admin.")
    else:
        ADMINS.add(user_id)
        save_admins()

        await tiers.promote_to_premium(user_id, bot=context.bot)
        await refresh_user_commands(user_id, bot=context.bot)
        await update.message.reply_text(f"✅ Added user {user_id} as admin.")

@restricted_to_super_admin
async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    if user_id not in ADMINS:
        await update.message.reply_text(f"ℹ️ User {user_id} is not an admin.")
    else:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_removeadmin:{user_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_removeadmin")
            ]
        ])
        await update.message.reply_text(
            f"⚠️ Are you sure you want to remove admin `{user_id}`?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@restricted_to_admin
async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMINS:
        await update.message.reply_text("📭 No admins currently set.")
        return

    msg = "👮‍♂️ *Current Admins:*\n"
    for admin_id in sorted(ADMINS):
        badge = "🌟 Super Admin" if admin_id == SUPER_ADMIN_ID else "👤 Admin"
        msg += f"- `{admin_id}` {badge}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# --- Callback for Remove Confirmation ---
@restricted_to_super_admin
async def handle_removeadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_removeadmin:"):
        user_id = int(query.data.split(":")[1])
        if user_id in ADMINS:
            ADMINS.remove(user_id)
            save_admins()
            await tiers.set_user_tier(user_id, "Apprentice", bot=context.bot)
            await refresh_user_commands(user_id, bot=context.bot)
            await query.edit_message_text(f"🗑️ Removed user {user_id} from admins.")
        else:
            await query.edit_message_text(f"ℹ️ User {user_id} is no longer an admin.")

    elif query.data == "cancel_removeadmin":
        await query.edit_message_text("❌ Admin removal cancelled.")


# --- Super Admin Command: Add wallet secret ---
@restricted_to_super_admin
async def addwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /aw <base58_secret_key1>,<base58_secret_key2>,...")
        return

    addresses_raw = " ".join(context.args)
    base58_keys = [key.strip() for key in addresses_raw.split(",") if key.strip()]

    if not base58_keys:
        await update.message.reply_text("❌ No valid secret keys provided.")
        return

    if os.path.exists(WALLET_SECRETS_FILE):
        with open(WALLET_SECRETS_FILE, "r") as f:
            secret_data = json.load(f)
    else:
        secret_data = {}

    added = []
    failed = []
    password = get_wallet_password()

    for base58_secret in base58_keys:
        try:
            secret_bytes = b58decode(base58_secret)
            keypair = Keypair.from_bytes(secret_bytes)
            address = str(keypair.pubkey())

            if address in secret_data:
                failed.append((address, "Already exists"))
                continue

            encrypted_key = encrypt_key(base58_secret, password)
            secret_data[address] = encrypted_key
            secrets_key.DECRYPTED_WALLETS[address] = base58_secret
            added.append(address)

        except Exception as e:
            failed.append((base58_secret[:6] + "...", str(e)))

    secrets_key.persist_encrypted_keys(secret_data)
    wallet_sync.sync_wallets_from_secrets()
    wallet_sync.purge_orphan_wallets()

    msg = ""
    if added:
        msg += "✅ Wallet(s) added successfully:\n" + "\n".join(added) + "\n\n"
    if failed:
        msg += "⚠️ Failed to add:\n" + "\n".join(f"{a} ({r})" for a, r in failed)

    await update.message.reply_text(msg.strip())

@restricted_to_super_admin
async def addpayout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addpayout <base58-private-key1>,<base58-private-key2>,...")
        return

    keys_raw = " ".join(context.args)
    keys = [k.strip() for k in keys_raw.split(",") if k.strip()]

    if not keys:
        await update.message.reply_text("❌ No valid private keys provided.")
        return

    await update.message.reply_text("⏳ Validating wallet private keys, please wait...")

    added, failed = [], []

    for key in keys:
        try:
            secret = b58decode(key)
            keypair = Keypair.from_bytes(secret)
            addr = str(keypair.pubkey())
            pubkey = Pubkey.from_string(addr)
        except Exception:
            failed.append((key, "Invalid base58 private key"))
            continue

        try:
            resp = SOLANA_CLIENT.get_account_info(pubkey)

            if resp is None or resp.value is None:
                # Wallet not on-chain yet — accept it since we have private key
                if add_wallet_to_payout_list(addr):
                    added.append(addr)
                else:
                    failed.append((addr, "Already exists"))
                continue

            owner = str(resp.value.owner)
            is_system_owned = owner == SYSTEM_PROGRAM_ID
            is_token_owned = owner == TOKEN_PROGRAM_ID
            data_len = len(resp.value.data) if hasattr(resp.value.data, '__len__') else 0
            is_executable = resp.value.executable

            if is_token_owned:
                failed.append((addr, "Address is owned by Token Program (token/mint account)"))
                continue

            if is_system_owned and data_len == 0 and not is_executable:
                if add_wallet_to_payout_list(addr):
                    added.append(addr)
                else:
                    failed.append((addr, "Already exists"))
            else:
                reason = "Not a user wallet"
                if not is_system_owned:
                    reason = f"Owned by non-System Program: {owner}"
                elif data_len > 0:
                    reason = f"Has data: {data_len} bytes"
                elif is_executable:
                    reason = "Executable account"
                failed.append((addr, reason))

        except Exception as e:
            failed.append((addr, str(e)))

    result_msg = ""
    if added:
        result_msg += f"✅ Added payout wallets:\n" + "\n".join(added) + "\n\n"
    if failed:
        result_msg += f"⚠️ Failed to add:\n" + "\n".join(f"{a} ({r})" for a, r in failed)

    await update.message.reply_text(result_msg.strip())

@restricted_to_admin
async def checkpayment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧍 Please enter the User ID of the user.")
    return ASK_USER_ID


async def receive_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["query_user_id"] = update.message.text.strip()
    await update.message.reply_text("📎 Now enter the Payment Reference ID.")
    return ASK_PAYMENT_ID


async def receive_payment_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_id = update.message.text.strip()
    user_id = context.user_data.get("query_user_id")
    logs = payment_logs.PAYMENT_LOGS.get(str(user_id), {})
    entry = logs.get(payment_id)
    action = entry.get('action') if entry.get('action') else "Upgrade"

    if not entry:
        await update.message.reply_text("❌ No matching payment log found.")
        return ConversationHandler.END

    msg = (
        f"📄 *Payment Log Found:*\n\n"
        f"📄 Action: {action}\n"
        f"👤 User ID: `{user_id}`\n"
        f"🆔 Payment ID: `{payment_id}`\n\n"
        f"💎 Tier: {entry.get('tier')}\n"
        f"⏳ Duration: {entry.get('duration_months')} month(s)\n\n"
        f"💰 Amount: {entry.get('amount_in_usdc')} USDC ≈ {entry.get('amount_in_sol')} SOL\n"
        f"🏦 Wallet: `{entry.get('payment_wallet')}`\n\n"
        f"🕓 Timestamp: {entry.get('start_time')}\n"
        f"🔗 TX Signature: `{entry.get('tx_sig', 'Not submitted')}`"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

check_payment_conv = ConversationHandler(
    entry_points=[
    CommandHandler("checkpayment", checkpayment),
    CommandHandler("cp", checkpayment)
    ],
    states={
        ASK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_user_id)],
        ASK_PAYMENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_id)],
    },
    fallbacks=[],
)

@restricted_to_admin
async def manualupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧍 Enter User ID for manual upgrade:")
    return MANUAL_USER_ID


async def manual_receive_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["manual_user_id"] = update.message.text.strip()
    await update.message.reply_text("🧾 Please enter the transaction signature:")
    return MANUAL_TX_SIG


async def manual_receive_tx_sig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["manual_tx_sig"] = update.message.text.strip()
    await update.message.reply_text("📎 Now enter the Payment Reference ID:")
    return MANUAL_PAYMENT_ID


async def manual_receive_payment_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_id = update.message.text.strip()
    user_id = context.user_data.get("manual_user_id")
    logs = payment_logs.PAYMENT_LOGS.get(str(user_id), {})
    payment = logs.get(payment_id)
    context.user_data["manual_payment_id"] = payment_id # Saving payment refernce to user data



    if not payment: 
        await update.message.reply_text("❌ Payment entry not found for the given user and reference.")
        return ConversationHandler.END

    tx_sig = context.user_data.get("manual_tx_sig")
    if tx_sig:
        payment["tx_sig"] = tx_sig

    await manual_upgrade.complete_verified_upgrade(int(user_id), payment, context)
    await update.message.reply_text("✅ Manual upgrade completed and payment forwarded.")
    return ConversationHandler.END

manual_upgrade_conv = ConversationHandler(
    entry_points=[
        CommandHandler("manualupgrade", manualupgrade),
        CommandHandler("mu", manualupgrade)
    ],
    states={
        MANUAL_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_receive_user_id)],
        MANUAL_TX_SIG: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_receive_tx_sig)],
        MANUAL_PAYMENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_receive_payment_id)],
    },
    fallbacks=[],
)


@restricted_to_admin
async def list_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view referral data for all users or a specific user."""
    
    
    # Ensure referral data is loaded
    referral.load_referral_data()
    
    # If no args, show summary of all referrers
    if not context.args:
        if not referral.REFERRAL_DATA:
            await update.message.reply_text("📊 No referral data found in the system.")
            return
            
        # Sort referrers by total commission (highest first)
        sorted_referrers = sorted(
            referral.REFERRAL_DATA.items(), 
            key=lambda x: x[1]["total_commission"], 
            reverse=True
        )
        
        msg = "📊 *Referral Program Summary*\n\n"
        
        for user_id, data in sorted_referrers[:5]:  # Show top 5
            try:
                user_info = await context.bot.get_chat(int(user_id))
                user_name = user_info.full_name or f"User {user_id}"
            except:
                user_name = f"User {user_id}"
            
                
            msg += (
                f"👤 *{user_name}* (ID: `{user_id}`)\n"
                f"  • Successful Referrals: {data['successful_referrals']}\n"
                f"  • Pending Referrals: {len(data['referred_users'])}\n"
                f"  • Total Commission: ${data['total_commission']:.2f}\n"
                #f"  • Paid: ${data['total_paid']:.2f}\n"
            )
            if data.get("tx_sig"):
                msg += (
                    f"  • Paid: ${data['total_paid']:.2f}\n"
                    f"  • Tx Sig: `{data['tx_sig']}`\n\n")
            else:
                msg += f"  • Paid: ${data['total_paid']:.2f}\n\n"
            
            
        msg += "\n\nUse `/listrefs <user_id>` to see details for a specific user."
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    else:
        # Show details for specific user
        user_id = context.args[0]
        
        if user_id not in referral.REFERRAL_DATA:
            await update.message.reply_text(f"❌ No referral data found for user ID {user_id}.")
            return
            
        data = referral.REFERRAL_DATA[user_id]
        
        try:
            user_info = await context.bot.get_chat(int(user_id))
            user_name = user_info.full_name or f"User {user_id}"
        except:
            user_name = f"User {user_id}"
            
        msg = f"📊 *Referral Data for {user_name}* (ID: `{user_id}`)\n\n"
        
        # User's data
        msg += (
            f"✅ Successful Referrals: {data['successful_referrals']}\n"
            f"🔄 Pending Referrals: {len(data['referred_users'])}\n\n"
            f"💰 Total Commission: ${data['total_commission']:.2f}\n"
            f"💵 Paid Amount: ${data['total_paid']:.2f}\n"
            f"💸 Unpaid Amount: ${data['total_commission'] - data['total_paid']:.2f}\n"
        )

        if data.get("tx_sig"):
                msg += f"\n🔗 Signature: `{data['tx_sig']}`\n"
        
        # Wallet info
        if data["wallet_address"]:
            msg += f"\n🔑 Wallet: `{data['wallet_address']}`\n"
        else:
            msg += "\n🔑 No wallet address set\n"
            
        
        await update.message.reply_text(msg, parse_mode="Markdown")

@restricted_to_admin
async def listwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to list all wallets (payout and regular) with pagination."""
    
    # Load wallet data from files
    payout_wallets = payout.get_payout_wallets()

    # Load decrypted secret wallets (from memory or disk)
    if not secrets_key.DECRYPTED_WALLETS:
        secret_data = secrets_key.load_encrypted_keys()
    else:
        secret_data = secrets_key.DECRYPTED_WALLETS
    
    # Store wallet data in user_data for pagination
    context.user_data['payout_wallets'] = payout_wallets
    context.user_data['secret_wallets'] = list(secret_data.keys())
    context.user_data['wallet_page'] = 0
    
    await show_wallet_dashboard(update, context)

async def show_wallet_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the wallet list with pagination."""
    payout_wallets = context.user_data.get('payout_wallets', [])
    secret_wallets = context.user_data.get('secret_wallets', [])
    page = context.user_data.get('wallet_page', 0)
    
    # Calculate total number of wallets
    total_wallets = len(payout_wallets) + len(secret_wallets)
    
    if total_wallets == 0:
        await update.message.reply_text("📭 No wallets configured.")
        return
    
    start_idx = page * WALLET_PAGE_SIZE
    end_idx = start_idx + WALLET_PAGE_SIZE
    
    # Determine which wallets to show on the current page
    # We prioritize payout wallets
    current_wallets = []
    payout_start = min(start_idx, len(payout_wallets))
    payout_end = min(end_idx, len(payout_wallets))
    
    # Add payout wallets for current page
    if payout_start < len(payout_wallets):
        current_wallets.extend([("payout", addr) for addr in payout_wallets[payout_start:payout_end]])
    
    # If we have space left, add regular wallets
    if end_idx > len(payout_wallets):
        secret_start = max(0, start_idx - len(payout_wallets))
        secret_end = max(0, end_idx - len(payout_wallets))
        if secret_start < len(secret_wallets):
            current_wallets.extend([("regular", addr) for addr in secret_wallets[secret_start:secret_end]])
    
    # Calculate total pages
    total_pages = (total_wallets - 1) // WALLET_PAGE_SIZE + 1
    
    # Build message
    msg = f"💼 *Wallet List* (Page {page + 1}/{total_pages})\n\n"
    
    for wallet_type, addr in current_wallets:
        if wallet_type == "payout":
            msg += f"💰 *Payout Wallet*: `{addr}`\n\n"
        else:
            msg += f"🔑 *Regular Wallet*: `{addr}`\n\n"
    
    # Build navigation buttons
    buttons = []
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⏮ Prev", callback_data=f"{LIST_WALLET_PAGE}_prev"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page + 1}/{total_pages}", callback_data="noop"))
    if end_idx < total_wallets:
        nav_buttons.append(InlineKeyboardButton("Next ⏭", callback_data=f"{LIST_WALLET_PAGE}_next"))
    
    buttons.append(nav_buttons)
    #buttons.append([InlineKeyboardButton("🏠 Back to Dashboard", callback_data="back_to_dashboard")])

    keyboard = InlineKeyboardMarkup(buttons)
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

async def handle_wallet_list_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle navigation buttons for wallet listing."""
    query = update.callback_query
    
    if query.data == f"{LIST_WALLET_PAGE}_prev":
        context.user_data['wallet_page'] = max(0, context.user_data.get('wallet_page', 0) - 1)
    elif query.data == f"{LIST_WALLET_PAGE}_next":
        payout_wallets = context.user_data.get('payout_wallets', [])
        secret_wallets = context.user_data.get('secret_wallets', [])
        total_wallets = len(payout_wallets) + len(secret_wallets)
        max_page = (total_wallets - 1) // WALLET_PAGE_SIZE
        context.user_data['wallet_page'] = min(max_page, context.user_data.get('wallet_page', 0) + 1)
    
    await show_wallet_dashboard(update, context)


@restricted_to_super_admin
async def removewallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove regular wallets (ones added by addwallet command)."""
    if not context.args:
        await update.message.reply_text("Usage: /removewallet <wallet_address1>,<wallet_address2>,...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("❌ No valid wallet addresses provided.")
        return

    if not secrets_key.DECRYPTED_WALLETS:
        secret_data = secrets_key.load_encrypted_keys()
    else:
        secret_data = secrets_key.DECRYPTED_WALLETS

    if not secret_data:
        await update.message.reply_text("❌ No wallet secrets found.")
        return


    # Identify removable and in-use addresses
    addresses_to_remove = []
    in_use_wallets = []
    not_found = []

    for addr in addresses:
        if addr not in secret_data:
            not_found.append(addr)
        elif wallet_sync.is_wallet_in_use(addr):
            in_use_wallets.append(addr)
        else:
            addresses_to_remove.append(addr)

    if not addresses_to_remove:
        msg = "❌ None of the provided addresses were eligible for removal."
        if not_found:
            msg += "\n\nAddresses not found:\n" + "\n".join(not_found)
        if in_use_wallets:
            msg += "\n\nWallets in use (skipped):\n" + "\n".join(in_use_wallets)
        await update.message.reply_text(msg)
        return

    confirmation_text = (
        f"⚠️ Are you sure you want to remove these {len(addresses_to_remove)} wallet(s)?\n\n" +
        "\n".join([f"- `{addr}`" for addr in addresses_to_remove])
    )

    if in_use_wallets:
        confirmation_text += (
            "\n\n🚫 The following wallet(s) are in use and will not be removed:\n" +
            "\n".join([f"- `{addr}`" for addr in in_use_wallets])
        )

    await confirm_action(
        update,
        context,
        confirm_callback_data=f"confirm_removewallet:{','.join(addresses_to_remove)}",
        cancel_callback_data="cancel_removewallet",
        confirm_message=confirmation_text
    )


@restricted_to_super_admin
async def handle_removewallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation for wallet removal."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_removewallet:"):
        addresses = query.data.split(":")[1].split(",")

        removed = []
        skipped = []

        for addr in addresses:
            if addr in secrets_key.DECRYPTED_WALLETS:
                if wallet_sync.is_wallet_in_use(addr):
                    skipped.append(addr)
                    continue
                del secrets_key.DECRYPTED_WALLETS[addr]
                removed.append(addr)

        if removed:
            password = get_wallet_password()
            encrypted_data = {
                a: encrypt_key(k, password)
                for a, k in secrets_key.DECRYPTED_WALLETS.items()
            }
            secrets_key.persist_encrypted_keys(encrypted_data)

            wallet_sync.sync_wallets_from_secrets()
            wallet_sync.purge_orphan_wallets()

            msg = f"✅ Successfully removed {len(removed)} wallet(s):\n" + "\n".join(f"`{addr}`" for addr in removed)
            if skipped:
                msg += ("\n\n🚫 Skipped in-use wallet(s):\n" + "\n".join(f"`{addr}`" for addr in skipped))
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ No wallets were removed.")

    elif query.data == "cancel_removewallet":
        await query.edit_message_text("❌ Wallet removal cancelled.")


@restricted_to_super_admin
async def removepayout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove payout wallets (ones added by addpayout command)."""
    if not context.args:
        await update.message.reply_text("Usage: /removepayout <wallet_address1>,<wallet_address2>,...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("❌ No valid wallet addresses provided.")
        return

    # Get current payout wallets
    payout_wallets = payout.get_payout_wallets()
    
    # Find which addresses actually exist in the payout list
    addresses_to_remove = [addr for addr in addresses if addr in payout_wallets]
    not_found = [addr for addr in addresses if addr not in payout_wallets]

    if not addresses_to_remove:
        msg = "❌ None of the provided addresses were found in the payout wallet list."
        if not_found:
            msg += "\n\nAddresses not found:\n" + "\n".join(not_found)
        await update.message.reply_text(msg)
        return

    confirmation_text = (
        f"⚠️ Are you sure you want to remove these {len(addresses_to_remove)} payout wallet(s)?\n\n" +
        "\n".join([f"- `{addr}`" for addr in addresses_to_remove])
    )

    await confirm_action(
        update,
        context,
        confirm_callback_data=f"confirm_removepayout:{','.join(addresses_to_remove)}",
        cancel_callback_data="cancel_removepayout",
        confirm_message=confirmation_text
    )

@restricted_to_super_admin
async def handle_removepayout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation for payout wallet removal."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_removepayout:"):
        addresses = query.data.split(":")[1].split(",")
        
        # Get current payout wallets
        current_wallets = payout.get_payout_wallets()
        
        # Remove specified wallets
        removed = []
        new_payout_list = []
        
        for addr in current_wallets:
            if addr in addresses:
                removed.append(addr)
            else:
                new_payout_list.append(addr)
        
        if removed:
            payout.PAYOUT_WALLETS = new_payout_list
            payout.save_payout_wallets()
            
            
            msg = f"✅ Successfully removed {len(removed)} payout wallet(s):\n" + "\n".join(f"`{addr}`" for addr in removed)
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ No payout wallets were removed.")

    elif query.data == "cancel_removepayout":
        await query.edit_message_text("❌ Payout wallet removal cancelled.")


def register_wallet_commands(app):
    """Register wallet management commands and their callbacks."""
    # Command handlers
    app.add_handler(CommandHandler(["listwallet", "lw"], listwallet))
    app.add_handler(CommandHandler(["removewallet", "rw"], removewallet))
    app.add_handler(CommandHandler(["removepayout", "rp"], removepayout))

    # Navigation callbacks
    app.add_handler(CallbackQueryHandler(
        handle_wallet_list_navigation, 
        pattern=f"^{LIST_WALLET_PAGE}_"
    ))

    # Confirmation callbacks
    app.add_handler(CallbackQueryHandler(
        handle_removewallet_callback, 
        pattern="^confirm_removewallet:|^cancel_removewallet$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_removepayout_callback, 
        pattern="^confirm_removepayout:|^cancel_removepayout$"
    ))
