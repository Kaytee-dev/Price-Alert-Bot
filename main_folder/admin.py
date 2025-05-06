from typing import Callable
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from util.utils import load_json, save_json, refresh_user_commands
from config import ADMINS_FILE, SUPER_ADMIN_ID, WALLET_SECRETS_FILE, SOLSCAN_BASE

import storage.tiers as tiers
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
MANUAL_USER_ID, MANUAL_PAYMENT_ID = range(2)

# User payment log query conversation states 
ASK_USER_ID, ASK_PAYMENT_ID = range(2)
ADMINS = set()

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
        await update.message.reply_text("Usage: /addpayout wallet1,wallet2,...")
        return

    addresses_raw = " ".join(context.args)
    addresses = [addr.strip() for addr in addresses_raw.split(",") if addr.strip()]

    if not addresses:
        await update.message.reply_text("❌ No valid wallet addresses provided.")
        return

    await update.message.reply_text("⏳ Validating wallet addresses, please wait...")

    added, failed = [], []

    for addr in addresses:
        # format check
        if not (32 <= len(addr) <= 44):
            failed.append((addr, "Invalid format or base58 length"))
            continue

        try:
            _ = Pubkey.from_string(addr)
        except Exception:
            failed.append((addr, "Invalid base58 public key"))
            continue

        try:
            url = SOLSCAN_BASE.format(addr)
            resp = requests.get(url, timeout=5)
            if resp.status_code != 404:
                if add_wallet_to_payout_list(addr):
                    added.append(addr)
                else:
                    failed.append((addr, "Already exists"))
            else:
                failed.append((addr, "Not indexed on Solscan"))
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
    await update.message.reply_text("📎 Now enter the Payment Reference ID:")
    return MANUAL_PAYMENT_ID


async def manual_receive_payment_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_id = update.message.text.strip()
    user_id = context.user_data.get("manual_user_id")
    logs = payment_logs.PAYMENT_LOGS.get(str(user_id), {})
    payment = logs.get(payment_id)

    if not payment: 
        await update.message.reply_text("❌ Payment entry not found for the given user and reference.")
        return ConversationHandler.END

    await manual_upgrade.complete_verified_upgrade(int(user_id), payment, context)
    await update.message.reply_text("✅ Manual upgrade completed and payment forwarded.")
    return ConversationHandler.END

manual_upgrade_conv = ConversationHandler(
    entry_points=[CommandHandler("manualupgrade", manualupgrade),
                  CommandHandler("mu", manualupgrade)],
    states={
        MANUAL_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_receive_user_id)],
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