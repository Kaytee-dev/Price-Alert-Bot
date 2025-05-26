from typing import Callable
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler, MessageHandler,
                          filters, CallbackQueryHandler
                          )
from util.utils import refresh_user_commands, confirm_action, build_custom_update_from_query
from config import (SUPER_ADMIN_ID, SOLANA_RPC,
                    TOKEN_PROGRAM_ID, SYSTEM_PROGRAM_ID, LIST_WALLET_PAGE, WALLET_PAGE_SIZE
                    )

import storage.tiers as tiers
import storage.payout as payout
import storage.user_collection as user_collection

from base58 import b58decode
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.api import Client

from pwd_loader.env_loader import get_wallet_password
from secrets_key import encrypt_key
from storage.payout import add_wallets_to_payout_bulk
import storage.rpcs as rpcs

import secrets_key as secrets_key
import util.wallet_sync as wallet_sync
import util.manual_upgrade as manual_upgrade
import storage.payment_logs as payment_logs
import logging

from telegram.error import BadRequest

from mongo_client import get_collection

# Manual upgrade conversation states
MANUAL_USER_ID, MANUAL_TX_SIG, MANUAL_PAYMENT_ID = range(3)

# User payment log query conversation states 
ASK_USER_ID, ASK_PAYMENT_ID = range(2)
ADMINS = set()

SOLANA_CLIENT = Client(SOLANA_RPC)

logger = logging.getLogger(__name__)

# --- Super Admin ID ---
#SUPER_ADMIN_ID = -4710110042  # Replace this with your actual ID

# --- Load/Save Admins ---
async def load_admins():
    """
    Async: Load the list of admin user_ids from MongoDB and ensure all are integers.
    """
    global ADMINS
    collection = get_collection("admins")
    doc = await collection.find_one({"_id": "admin_list"})
    
    if doc and "user_ids" in doc:
        # Cast all user IDs to int safely
        ADMINS = set(int(uid) for uid in doc["user_ids"])
    else:
        ADMINS = set()

    ADMINS.add(int(SUPER_ADMIN_ID))
    logger.info("✅ ADMINS loaded from admins collection")

async def save_admins():
    """
    Async: Save ADMINS to MongoDB and refresh cache.
    """
    global ADMINS
    collection = get_collection("admins")
    await collection.update_one(
        {"_id": "admin_list"},
        {"$set": {"user_ids": list(ADMINS)}},
        upsert=True
    )
    # Refresh cache from what was saved
    ADMINS = set(ADMINS)
    ADMINS.add(SUPER_ADMIN_ID)

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
        await save_admins()

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
            await save_admins()
            await tiers.set_user_tier(user_id, "apprentice", bot=context.bot)
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

    # Ensure DECRYPTED_WALLETS is populated
    await secrets_key.load_encrypted_keys()

    added = []
    failed = []
    password = get_wallet_password()

    # Fetch existing secrets from cache
    secret_data = {
        address: encrypt_key(key, password)
        for address, key in secrets_key.DECRYPTED_WALLETS.items()
    }

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

    await secrets_key.persist_encrypted_keys(secret_data)
    await wallet_sync.sync_wallets_from_secrets()
    await wallet_sync.purge_orphan_wallets()

    msg = ""
    if added:
        msg += "✅ Wallet(s) added successfully:\n" + "\n".join(added) + "\n\n"
    if failed:
        msg += "⚠️ Failed to add:\n" + "\n".join(f"{a} ({r})" for a, r in failed)

    await update.message.reply_text(msg.strip())

@restricted_to_super_admin
# async def addpayout(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not context.args:
#         await update.message.reply_text("Usage: /addpayout <base58-private-key1>,<base58-private-key2>,...")
#         return

#     keys_raw = " ".join(context.args)
#     keys = [k.strip() for k in keys_raw.split(",") if k.strip()]

#     if not keys:
#         await update.message.reply_text("❌ No valid private keys provided.")
#         return

#     await update.message.reply_text("⏳ Validating wallet private keys, please wait...")

#     added, failed = [], []

#     for key in keys:
#         try:
#             secret = b58decode(key)
#             keypair = Keypair.from_bytes(secret)
#             addr = str(keypair.pubkey())
#             pubkey = Pubkey.from_string(addr)
#         except Exception:
#             failed.append((key, "Invalid base58 private key"))
#             continue

#         try:
#             resp = SOLANA_CLIENT.get_account_info(pubkey)

#             if resp is None or resp.value is None:
#                 # Wallet not on-chain yet — accept it since we have private key
#                 if add_wallet_to_payout_list(addr):
#                     added.append(addr)
#                 else:
#                     failed.append((addr, "Already exists"))
#                 continue

#             owner = str(resp.value.owner)
#             is_system_owned = owner == SYSTEM_PROGRAM_ID
#             is_token_owned = owner == TOKEN_PROGRAM_ID
#             data_len = len(resp.value.data) if hasattr(resp.value.data, '__len__') else 0
#             is_executable = resp.value.executable

#             if is_token_owned:
#                 failed.append((addr, "Address is owned by Token Program (token/mint account)"))
#                 continue

#             if is_system_owned and data_len == 0 and not is_executable:
#                 if add_wallet_to_payout_list(addr):
#                     added.append(addr)
#                 else:
#                     failed.append((addr, "Already exists"))
#             else:
#                 reason = "Not a user wallet"
#                 if not is_system_owned:
#                     reason = f"Owned by non-System Program: {owner}"
#                 elif data_len > 0:
#                     reason = f"Has data: {data_len} bytes"
#                 elif is_executable:
#                     reason = "Executable account"
#                 failed.append((addr, reason))

#         except Exception as e:
#             failed.append((addr, str(e)))

#     result_msg = ""
#     if added:
#         result_msg += f"✅ Added payout wallets:\n" + "\n".join(added) + "\n\n"
#     if failed:
#         result_msg += f"⚠️ Failed to add:\n" + "\n".join(f"{a} ({r})" for a, r in failed)

#     await update.message.reply_text(result_msg.strip())
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

    added, failed, valid_new = [], [], []

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
                valid_new.append(addr)
                continue

            owner = str(resp.value.owner)
            is_system_owned = owner == SYSTEM_PROGRAM_ID
            is_token_owned = owner == TOKEN_PROGRAM_ID
            data_len = len(resp.value.data) if hasattr(resp.value.data, '__len__') else 0
            is_executable = resp.value.executable

            if is_token_owned:
                failed.append((addr, "Address is owned by Token Program (token/mint account)"))
            elif is_system_owned and data_len == 0 and not is_executable:
                valid_new.append(addr)
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

    # Bulk add new addresses
    actually_added = await add_wallets_to_payout_bulk(valid_new)
    added.extend(actually_added)

    already_exist = list(set(valid_new) - set(actually_added))
    for dup in already_exist:
        failed.append((dup, "Already exists"))

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
        # Persist the changes to database
        await payment_logs.log_user_payment(user_id, payment_id, payment)

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
    
    await user_collection.load_user_collection_from_mongo()

    # Filter users that have a referral section
    referral_users = {
        uid: doc["referral"]
        for uid, doc in user_collection.USER_COLLECTION.items()
        if "referral" in doc
    }

    if not context.args:
        if not referral_users:
            await update.message.reply_text("📊 No referral data found in the system.")
            return

        # Sort by total_commission
        sorted_referrers = sorted(
            referral_users.items(),
            key=lambda x: x[1].get("total_commission", 0),
            reverse=True
        )

        msg = "📊 *Referral Program Summary*\n\n"

        for user_id, data in sorted_referrers[:5]:  # top 5
            try:
                user_info = await context.bot.get_chat(int(user_id))
                user_name = user_info.full_name or f"User {user_id}"
            except:
                user_name = f"User {user_id}"

            msg += (
                f"👤 *{user_name}* (ID: `{user_id}`)\n"
                f"  • All Time Referrals: {data.get('total_referred', 0)}\n"
                f"  • Successful Referrals: {data.get('successful_referrals', 0)}\n"
                f"  • Pending Referrals: {len(data.get('referred_users', []))}\n"
                f"  • Total Commission: ${data.get('total_commission', 0):.2f}\n"
                f"  • Paid: ${data.get('total_paid', 0):.2f}\n"
            )

            if data.get("tx_sig"):
                msg += f"  • Tx Sig: `{data['tx_sig']}`\n"

            msg += "\n"

        msg += "\nUse `/listrefs <user_id>` to see details for a specific user."
        await update.message.reply_text(msg.strip(), parse_mode="Markdown")

    else:
        user_id = context.args[0]

        if user_id not in user_collection.USER_COLLECTION or "referral" not in user_collection.USER_COLLECTION[user_id]:
            await update.message.reply_text(f"❌ No referral data found for user ID {user_id}.")
            return

        data = user_collection.USER_COLLECTION[user_id]["referral"]

        try:
            user_info = await context.bot.get_chat(int(user_id))
            user_name = user_info.full_name or f"User {user_id}"
        except:
            user_name = f"User {user_id}"

        msg = f"📊 *Referral Data for {user_name}* (ID: `{user_id}`)\n\n"
        msg += (
            f"👤 All Time Referrals: {data.get('total_referred', 0)}\n"
            f"✅ Successful Referrals: {data.get('successful_referrals', 0)}\n"
            f"🔄 Pending Referrals: {len(data.get('referred_users', []))}\n\n"
            f"💰 Total Commission: ${data.get('total_commission', 0):.2f}\n"
            f"💵 Paid Amount: ${data.get('total_paid', 0):.2f}\n"
            f"💸 Unpaid Amount: ${(data.get('total_commission', 0) - data.get('total_paid', 0)):.2f}\n"
        )

        if data.get("tx_sig"):
            msg += f"\n🔗 Signature: `{data['tx_sig']}`\n"

        if data.get("wallet_address"):
            msg += f"\n🔑 Wallet: `{data['wallet_address']}`\n"
        else:
            msg += "\n🔑 No wallet address set\n"

        await update.message.reply_text(msg.strip(), parse_mode="Markdown")



@restricted_to_super_admin
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
        current_wallets.extend([("withdrawal", addr) for addr in payout_wallets[payout_start:payout_end]])
    
    # If we have space left, add regular wallets
    if end_idx > len(payout_wallets):
        secret_start = max(0, start_idx - len(payout_wallets))
        secret_end = max(0, end_idx - len(payout_wallets))
        if secret_start < len(secret_wallets):
            current_wallets.extend([("deposit", addr) for addr in secret_wallets[secret_start:secret_end]])
    
    # Calculate total pages
    total_pages = (total_wallets - 1) // WALLET_PAGE_SIZE + 1
    
    # Build message
    msg = f"💼 *Wallet List* (Page {page + 1}/{total_pages})\n\n"
    
    for wallet_type, addr in current_wallets:
        if wallet_type == "withdrawal":
            msg += f"💰 *Withdrawal Wallet*: `{addr}`\n\n"
        else:
            msg += f"🔑 *Deposit Wallet*: `{addr}`\n\n"
    
    # Build navigation buttons
    buttons = []
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⏮ Prev", callback_data=f"{LIST_WALLET_PAGE}_prev"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page + 1}/{total_pages}", callback_data="noop"))
    if end_idx < total_wallets:
        nav_buttons.append(InlineKeyboardButton("Next ⏭", callback_data=f"{LIST_WALLET_PAGE}_next"))
    
    buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🏠 Back to Dashboard", callback_data="to_dashboard")])

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

    if query.data == "to_dashboard":
        await query.answer()
        # Delete the current message containing the token list
        #context.user_data.clear()
        await query.message.delete()
        # Directly call the launch function after deletion
        launch_func = context.bot_data.get("launch_dashboard")

        if launch_func:
            await launch_func(update, context)
            return
        else:
            try:
                await update.callback_query.edit_message_text("⚠️ Dashboard unavailable.")
            except BadRequest as e:
                if "message to edit" in str(e):
                    await update.effective_chat.send_message("⚠️ Dashboard unavailable.")
                else:
                    raise
        return
    
    elif query.data == f"{LIST_WALLET_PAGE}_prev":
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

    # Always refresh DECRYPTED_WALLETS to ensure consistency
    secret_data = await secrets_key.load_encrypted_keys()
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
            await secrets_key.persist_encrypted_keys(encrypted_data)

            await wallet_sync.sync_wallets_from_secrets()
            await wallet_sync.purge_orphan_wallets()

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
        
        removed = await payout.remove_wallets_from_payout(addresses)

        if removed:
            msg = f"✅ Successfully removed {len(removed)} payout wallet(s):\n" + "\n".join(f"`{addr}`" for addr in removed)
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ No payout wallets were removed.")

    elif query.data == "cancel_removepayout":
        await query.edit_message_text("❌ Payout wallet removal cancelled.")


@restricted_to_admin
async def addrpc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addrpc <rpc1>,<rpc2>,...")
        return

    if not rpcs.RPC_LIST:
        await rpcs.load_rpc_list()
    raw_input = " ".join(context.args)
    new_rpcs = [rpc.strip() for rpc in raw_input.split(",") if rpc.strip()]
    
    added = await rpcs.add_rpcs_bulk(new_rpcs)
    skipped = list(set(new_rpcs) - set(added))

    msg = ""
    if added:
        msg += f"✅ Added RPC(s):\n" + "\n".join(added) + "\n\n"
    if skipped:
        msg += f"⚠️ Already present:\n" + "\n".join(skipped)
    await update.message.reply_text(msg.strip())


@restricted_to_admin
async def removerpc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removerpc <rpc1>,<rpc2>,...")
        return

    if not rpcs.RPC_LIST:
        await rpcs.load_rpc_list()
    raw_input = " ".join(context.args)
    to_remove = [rpc.strip() for rpc in raw_input.split(",") if rpc.strip()]
    
    found = [rpc for rpc in to_remove if rpc in rpcs.RPC_LIST]
    not_found = [rpc for rpc in to_remove if rpc not in rpcs.RPC_LIST]

    if not found:
        msg = "❌ None of the provided RPCs were found in the list."
        if not_found:
            msg += "\n\nMissing:\n" + "\n".join(not_found)
        await update.message.reply_text(msg)
        return

    confirmation = (
        f"⚠️ Are you sure you want to remove these {len(found)} RPC(s)?\n\n" +
        "\n".join([f"- `{rpc}`" for rpc in found])
    )

    await confirm_action(
        update,
        context,
        confirm_callback_data=f"confirm_removerpc:{','.join(found)}",
        cancel_callback_data="cancel_removerpc",
        confirm_message=confirmation
    )


@restricted_to_admin
async def handle_removerpc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_removerpc:"):
        to_remove = query.data.split(":")[1].split(",")

        removed = await rpcs.remove_rpcs_bulk(to_remove)

        if removed:
            msg = f"✅ Successfully removed {len(removed)} RPC(s):\n" + "\n".join(f"`{rpc}`" for rpc in removed)
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ No RPCs were removed.")

    elif query.data == "cancel_removerpc":
        await query.edit_message_text("❌ RPC removal cancelled.")


@restricted_to_admin
async def listrpc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Step 1: Check if RPC_LIST is empty and load if needed
    if not rpcs.RPC_LIST:
        await rpcs.load_rpc_list()

    # Step 2: If still empty, notify user
    if not rpcs.RPC_LIST:
        await update.message.reply_text("ℹ️ No RPC endpoints found.")
        return

    # Step 3: Display the list
    rpc_list = "\n".join([f"{i+1}. {rpc}" for i, rpc in enumerate(rpcs.RPC_LIST)])
    await update.message.reply_text(f"📡 Current RPC Endpoints:\n{rpc_list}")


def register_wallet_commands(app):
    """Register wallet management commands and their callbacks."""
    # Command handlers
    app.add_handler(CommandHandler(["listwallet", "lw"], listwallet))
    app.add_handler(CommandHandler(["removewallet", "rw"], removewallet))
    app.add_handler(CommandHandler(["removepayout", "rp"], removepayout))

    # Navigation callbacks
    app.add_handler(CallbackQueryHandler(
        handle_wallet_list_navigation, 
        pattern=f"^{LIST_WALLET_PAGE}_|^to_dashboard$"
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
