import logging
from typing import Dict, List, Tuple, Set, Any
import asyncio
import json
from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    MessageHandler, filters, CallbackQueryHandler
)
from telegram.constants import ChatAction

from admin import restricted_to_admin

# Import wallet validation tools from admin.py
from base58 import b58decode
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.api import Client
import secrets_key as secrets_key
import requests

import referral as referral
from upgrade import fetch_sol_price_usd
from config import SOLSCAN_BASE, SOLSCAN_TX_BASE, SOLANA_RPC, BOT_NAME
from util.process_batch_payout_util import process_batch_payouts
from util.wallet_validator import validate_wallet_addresses

import storage.user_collection as user_collection

logger = logging.getLogger(__name__)

# Constants
MIN_PAYOUT_THRESHOLD = 0.005  # Minimum payout in SOL
NETWORK_FEE_PER_TX = 0.000005  # SOL fee per transaction
MIN_SUCCESSFUL_REFERRALS = 5  # Minimum successful referrals to be eligible

# States for the payout conversation
NOTIFY_MISSING_WALLET, CONFIRM_PAYOUT, ENTER_WALLET_KEY = range(3)

# Determine if we're on mainnet or devnet
IS_MAINNET = "mainnet" in SOLANA_RPC.lower()
CLUSTER = "mainnet" if IS_MAINNET else "devnet"

# Filter eligible users for payout
def get_eligible_users() -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, Dict[str, Any]]]]:
    eligible_users = []
    eligible_without_wallet = []

    for user_id, doc in user_collection.USER_COLLECTION.items():
        referral_data = doc.get("referral", {})
        total_commission = referral_data.get("total_commission", 0.0)
        total_paid = referral_data.get("total_paid", 0.0)
        wallet_address = referral_data.get("wallet_address", "")
        successful_referrals = referral_data.get("successful_referrals", 0)

        unpaid_commission = total_commission - total_paid

        if unpaid_commission > 0 and successful_referrals >= MIN_SUCCESSFUL_REFERRALS:
            if wallet_address:
                eligible_users.append((user_id, referral_data))
            else:
                eligible_without_wallet.append((user_id, referral_data))

    return eligible_users, eligible_without_wallet


async def calculate_payout_totals(valid_users: List[Tuple[str, Dict[str, Any]]]) -> Tuple[int, float, float, float, float]:
    total_users = len(valid_users)
    total_commission_usd = sum(data["total_commission"] - data["total_paid"] for _, data in valid_users)
    sol_usd_price = await fetch_sol_price_usd()
    network_fee_base = NETWORK_FEE_PER_TX * sol_usd_price
    network_fees = total_users * network_fee_base
    network_fees_sol = network_fees / sol_usd_price
    total_cost = total_commission_usd + network_fees  # No conversion to SOL

    return total_users, total_commission_usd, network_fees, network_fees_sol, total_cost


# Notify users about missing wallet
async def notify_users_missing_wallet(context: ContextTypes.DEFAULT_TYPE, eligible_without_wallet: List[Tuple[str, Dict[str, Any]]]):
    for user_id, data in eligible_without_wallet:
        try:
            unpaid_commission = data["total_commission"] - data["total_paid"]
            message = (
                "💰 *You're eligible for a referral commission payout!*\n\n"
                f"You have ${unpaid_commission:.2f} in unpaid referral commissions ready to be paid out.\n\n"
                "To ensure your payout will be processed in the next round of payout, "
                "kindly link your USDC wallet address on Solana network using the referral page."
            )
            
            await context.bot.send_message(
                chat_id=int(user_id),
                text=message,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about missing wallet: {str(e)}")


# Handle notification selection
async def handle_notification_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "notify_missing_wallet":
        eligible_without_wallet = context.user_data.get("eligible_without_wallet", [])
        
        if not eligible_without_wallet:
            await query.edit_message_text("No eligible users without wallets found.")
            return CONFIRM_PAYOUT
        
        # Show processing message
        await query.edit_message_text(f"⏳ Sending notifications to {len(eligible_without_wallet)} users...")
        
        # Notify users
        await notify_users_missing_wallet(context, eligible_without_wallet)
        
        # Confirm completion
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Notifications sent to {len(eligible_without_wallet)} users."
        )
    else:  # skip_notifications
        await query.edit_message_text("Notifications skipped.")
    
    # Continue with the normal payout flow
    # Get eligible users (with wallets)
    eligible_users = context.user_data.get("eligible_users", [])
    
    # Show processing message
    processing_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ Validating wallet addresses, please wait..."
    )
    
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Initialize set of notified users if not exists
    if "invalid_wallet_notified" not in context.user_data:
        context.user_data["invalid_wallet_notified"] = set()

    # Validate wallet addresses
    valid_users, invalid_users = await validate_wallet_addresses(eligible_users)
    
    # Automatically notify users with invalid wallets
    if invalid_users:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⏳ Sending notifications to users with invalid wallets..."
        )
        
        # Notify users with invalid wallets
        newly_notified = await notify_users_invalid_wallet(
            context, 
            invalid_users, 
            context.user_data["invalid_wallet_notified"]
        )
        
        if newly_notified > 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ Notifications sent to {newly_notified} users with invalid wallets."
            )

    if not valid_users:
        await processing_msg.edit_text(
            "❌ No users have valid wallet addresses for payout.\n\n"
            f"Invalid wallets: {len(invalid_users)}"
        )
        return ConversationHandler.END
    
    # Calculate payout totals
    total_users, total_usd, network_fees, network_fees_sol, total_cost = await calculate_payout_totals(valid_users)
    
    # Store data in context for later use
    context.user_data["valid_users"] = valid_users
    context.user_data["invalid_users"] = invalid_users
    
    # Create summary message
    summary = (
        f"📊 *Referral Payout Summary*\n\n"
        f"🧑‍🤝‍🧑 Eligible Users: {total_users}\n"
        f"💲 Total Commission (USD): ${total_usd:.2f}\n"
        f"🔄 Network Fees: {network_fees:.6f} USD (~ {network_fees_sol:.6f} SOL)\n"
        f"💵 *Total Cost: {total_cost:.6f} SOL*\n\n"
    )
    
    if invalid_users:
        summary += f"⚠️ {len(invalid_users)} users have invalid wallet addresses and will be skipped.\n\n"
    
    summary += (
        "Would you like to proceed with processing these payments?\n\n"
        "⚠️ *IMPORTANT*: Once confirmed, you will be prompted to enter the payout wallet's private key."
    )
    
    # Update the processing message with the summary
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm Payout", callback_data="confirm_payout"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_payout")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await processing_msg.edit_text(
        text=summary,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return CONFIRM_PAYOUT


# Main command handler
@restricted_to_admin
async def process_referral_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_collection.USER_COLLECTION:
        await update.message.reply_text("📊 No referral data found in the system.")
        return ConversationHandler.END


    # Get eligible users
    eligible_users, eligible_without_wallet = get_eligible_users()

    # Store eligible users in context for later use
    context.user_data["eligible_users"] = eligible_users
    context.user_data["eligible_without_wallet"] = eligible_without_wallet

    if not eligible_users and not eligible_without_wallet:
        await update.message.reply_text(
            "❌ No users currently meet the payout criteria.\n\n"
            f"Requirements:\n"
            f"- Minimum {MIN_SUCCESSFUL_REFERRALS} successful referrals\n"
            f"- Unpaid commission > 0"
        )
        return ConversationHandler.END

    # Handle users without wallets first if there are any
    if eligible_without_wallet:
        keyboard = [
            [
                InlineKeyboardButton("📧 Notify These Users", callback_data="notify_missing_wallet"),
                InlineKeyboardButton("❌ Skip Notifications", callback_data="skip_notifications")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"⚠️ {len(eligible_without_wallet)} users are eligible for payout but haven't linked their wallet.",
            reply_markup=reply_markup
        )

        return NOTIFY_MISSING_WALLET

    # If no users without wallets, proceed with normal flow
    # Show processing message
    processing_msg = await update.message.reply_text(
        "⏳ Validating wallet addresses, please wait..."
    )

    # Get chat ID for showing typing indicator
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Initialize set of notified users if not exists
    if "invalid_wallet_notified" not in context.user_data:
        context.user_data["invalid_wallet_notified"] = set()

    asyncio.create_task(
        run_wallet_validation_background(context, chat_id, eligible_users, processing_msg)
    )
    return CONFIRM_PAYOUT


async def notify_invalid_wallets_background(context, chat_id, invalid_users):
    try:
        await context.bot.send_message(chat_id, "⏳ Notifying users with invalid wallets...")

        newly_notified = await notify_users_invalid_wallet(
            context,
            invalid_users,
            context.user_data["invalid_wallet_notified"]
        )

        if newly_notified > 0:
            await context.bot.send_message(
                chat_id,
                f"✅ Notifications sent to {newly_notified} users with invalid wallets."
            )
        else:
            await context.bot.send_message(
                chat_id,
                f"❌ No notification were sent to {len(invalid_users)} users with invalid wallets."
            )
    except Exception as e:
        logger.error(f"❌ Failed to notify users with invalid wallets: {e}")


async def run_wallet_validation_background(context: ContextTypes.DEFAULT_TYPE, chat_id, eligible_users, processing_msg):
    try:
        valid_users, invalid_users = await validate_wallet_addresses(eligible_users, processing_msg)

        #valid_users, invalid_users = await validate_wallet_addresses(eligible_users)
        context.user_data["valid_users"] = valid_users
        context.user_data["invalid_users"] = invalid_users

        if invalid_users:
            asyncio.create_task(
                notify_invalid_wallets_background(context, chat_id, invalid_users)
            )


        if not valid_users:
            await processing_msg.edit_text(
                "❌ No users have valid wallet addresses for payout.\n\n"
                f"Invalid wallets: {len(invalid_users)}"
            )
            return

        # Calculate payout totals
        total_users, total_usd, network_fees, network_fees_sol, total_cost = await calculate_payout_totals(valid_users)

        # Create summary message
        summary = (
            f"📊 *Referral Payout Summary*\n\n"
            f"🧑‍🤝‍🧑 Eligible Users: {total_users}\n"
            f"💲 Total Commission (USD): ${total_usd:.2f}\n"
            f"🔄 Network Fees: {network_fees:.6f} USD (~ {network_fees_sol:.6f} SOL)\n"
            f"💵 *Total Cost: {total_cost:.6f} USD*\n\n"
        )

        if invalid_users:
            summary += f"⚠️ {len(invalid_users)} users have invalid wallet addresses and will be skipped.\n\n"

        
        summary += (
            "Would you like to proceed with processing these payments?\n\n"
            "⚠️ *IMPORTANT*: Once confirmed, you will be prompted to enter the payout wallet's private key."
        )

        # Update the processing message with the summary
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm Payout", callback_data="confirm_payout"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_payout")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await processing_msg.edit_text(
            text=summary,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Wallet validation task failed: {e}")
        await processing_msg.edit_text(f"❌ Wallet validation failed:\n{str(e)}")


# Handle payout confirmation
async def handle_confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_payout":
        await query.edit_message_text(
            "❌ Payout process cancelled."
        )
        return ConversationHandler.END
    
    await query.edit_message_text(
        "🔑 Please enter the base58 private key of the wallet to send payments from.\n\n"
        "⚠️ *SECURITY WARNING*: This key will only be used for this transaction batch and "
        "will not be stored permanently.\n\n"
        "Type /cancel to abort this operation."
    )
    
    return ENTER_WALLET_KEY

# Handle wallet key input
async def handle_wallet_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Delete the message containing the private key for security
    await update.message.delete()
    
    # Get the key from the message
    base58_key = update.message.text.strip()
    
    try:
        # Validate the key
        secret_bytes = b58decode(base58_key)
        keypair = Keypair.from_bytes(secret_bytes)
        sender_address = str(keypair.pubkey())
        
        # Store keypair in context (it will be deleted after operation)
        context.user_data["payout_keypair"] = keypair
        context.user_data["sender_address"] = sender_address
        
        # Send processing message
        processing_msg = await update.message.reply_text(
            f"✅ Valid wallet key provided. Sender address: `{sender_address[:6]}...{sender_address[-4:]}`\n\n"
            "⏳ Starting payout processing...",
            parse_mode="Markdown"
        )
        
        # Store processing message for updates
        context.user_data["processing_msg"] = processing_msg
        
        # Start the payout processing
        return await process_payments(update, context)
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Invalid wallet key: {str(e)}\n\n"
            "Please try again with a valid base58 private key or type /cancel to abort."
        )
        return ENTER_WALLET_KEY

# Process all payments
async def process_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    valid_users = context.user_data.get("valid_users", [])
    keypair = context.user_data.get("payout_keypair")
    processing_msg = context.user_data.get("processing_msg")
    
    if not valid_users or not keypair or not processing_msg:
        await update.message.reply_text("❌ Missing required data for payout processing.")
        return ConversationHandler.END
    
    # Update processing message
    await processing_msg.edit_text(
        f"⏳ Preparing to process {len(valid_users)} payments in batches..."
    )
    
    # Prepare payment batch data
    payment_batch = []
    for user_id, data in valid_users:
        # Calculate unpaid commission
        unpaid_commission = data["total_commission"] - data["total_paid"]
        amount_usd = unpaid_commission
        wallet_address = data["wallet_address"]
        
        payment_batch.append((user_id, wallet_address, amount_usd))
    
    # Process payments in batch
    await processing_msg.edit_text(
        f"⏳ Processing {len(payment_batch)} payments in optimized batches..."
    )
    
    # Import the batch processing function
    
    
    # Process the payments in batch
    results = await process_batch_payouts(payment_batch, keypair, context)
    
    # Parse results
    successful_transfers = []
    failed_transfers = []

    # Prepare bulk updates
    bulk_updates = []
    
    for user_id, success, tx_sig, message in results:
        user_doc = user_collection.USER_COLLECTION.get(user_id, {})
        referral_data = user_doc.get("referral", {})
        # Find the data for this user
        user_data = next((data for uid, data in valid_users if uid == user_id), None)
        
        if not user_data:
            continue
            
        # Calculate unpaid commission
        unpaid_commission = user_data["total_commission"] - user_data["total_paid"]
        amount_usd = unpaid_commission
        
        if success:
            # Update referral data to database
            # referral_data["total_paid"] = referral_data.get("total_paid", 0.0) + unpaid_commission
            # referral_data["successful_referrals"] = 0
            # referral_data["tx_sig"] = tx_sig
            # await user_collection.update_user_fields(user_id, {"referral": referral_data})

            bulk_updates.append({
            "_id": user_id,
            "fields": {
                "referral.total_paid": referral_data.get("total_paid", 0.0) + unpaid_commission,
                "referral.tx_sig": tx_sig,
                "referral.successful_referrals": 0
            }
            })

            successful_transfers.append((user_id, amount_usd, tx_sig))
        else:
            failed_transfers.append((user_id, amount_usd, message))
    
    # Perform bulk update
    if bulk_updates:
        await user_collection.bulk_update_user_fields(bulk_updates)

    # Create summary message
    summary = (
        f"✅ *Referral Payout Complete*\n\n"
        f"✅ Successful transfers: {len(successful_transfers)}\n"
        f"❌ Failed transfers: {len(failed_transfers)}\n\n"
    )
    
    # Add details about successful transfers
    if successful_transfers:
        summary += "*Successful Transfers:*\n"
        for i, (user_id, amount, tx_sig) in enumerate(successful_transfers[:5]):  # Show only first 5
            summary += f"{i+1}. User ID: {user_id} - {amount:.2f} USD - [TX]({SOLSCAN_TX_BASE.format(tx_sig)}?cluster={CLUSTER})\n"
        
        if len(successful_transfers) > 5:
            summary += f"...and {len(successful_transfers) - 5} more\n"
        
        summary += "\n"
    
    # Add details about failed transfers
    if failed_transfers:
        summary += "*Failed Transfers:*\n"
        for i, (user_id, amount, error) in enumerate(failed_transfers[:5]):  # Show only first 5
            summary += f"{i+1}. User ID: {user_id} - {amount:.2f} USD - Error: {error}\n"
        
        if len(failed_transfers) > 5:
            summary += f"...and {len(failed_transfers) - 5} more\n"
    
    # Clean up sensitive data
    if "payout_keypair" in context.user_data:
        del context.user_data["payout_keypair"]
    
    # Update processing message with final summary
    await processing_msg.edit_text(
        text=summary,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    
    # Also notify users about their payouts
    await notify_users_about_payouts(context, successful_transfers)
    
    return ConversationHandler.END

# Notify users about their payouts
async def notify_users_about_payouts(context: ContextTypes.DEFAULT_TYPE, successful_transfers: List[Tuple[str, float, str]]):
    for user_id, amount_usd, tx_sig in successful_transfers:
        try:
            message = (
                "💰 *Referral Commission Payout Received!*\n\n"
                f"You've received a referral commission payout of *${amount_usd:.2f}* .\n\n"
                f"Transaction: [View on Solscan]({SOLSCAN_TX_BASE.format(tx_sig)}?cluster={CLUSTER})\n\n"
                f"Thanks for being a valuable part of {BOT_NAME} community! Continue referring users to earn more rewards."
            )
            
            await context.bot.send_message(
                chat_id=int(user_id),
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about payout: {str(e)}")


# Function to notify users about invalid wallet addresses
async def notify_users_invalid_wallet(context: ContextTypes.DEFAULT_TYPE, invalid_users: List[Tuple[str, str]], already_notified_set: Set[str]):
    newly_notified = 0
    
    for user_id, error_reason in invalid_users:
        # Skip if already notified
        if user_id in already_notified_set:
            continue
            
        try:
            # Get user data
            user_doc = user_collection.USER_COLLECTION.get(user_id, {})
            referral_data = user_doc.get("referral", {})
            unpaid_commission = referral_data.get("total_commission", 0) - referral_data.get("total_paid", 0)

            message = (
                "⚠️ *Your wallet address needs attention*\n\n"
                f"You have ${unpaid_commission:.2f} in unpaid referral commissions ready to be paid out, "
                f"but we couldn't process your payment due to an issue with your wallet address.\n\n"
                f"*Error: {error_reason}*\n\n"
                "Please update your USDC wallet address on Solana network on the referral page to ensure "
                "you receive your referral commission in the next payout round."
            )
            
            await context.bot.send_message(
                chat_id=int(user_id),
                text=message,
                parse_mode="Markdown"
            )
            
            # Mark as notified
            already_notified_set.add(user_id)
            newly_notified += 1
            
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about invalid wallet: {str(e)}")
    
    return newly_notified


# Cancel handler
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Clean up sensitive data
    if "payout_keypair" in context.user_data:
        del context.user_data["payout_keypair"]
    
    await update.message.reply_text(
        "❌ Payout process cancelled."
    )
    return ConversationHandler.END

# Create the conversation handler
payout_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("processpayouts", process_referral_payouts),
        CommandHandler("pp", process_referral_payouts)
    ],
    states={
        NOTIFY_MISSING_WALLET: [
            CallbackQueryHandler(handle_notification_selection, pattern="^notify_missing_wallet$|^skip_notifications$")
        ],
        CONFIRM_PAYOUT: [
            CallbackQueryHandler(handle_confirm_payout, pattern="^confirm_payout$|^cancel_payout$")
        ],
        ENTER_WALLET_KEY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_key_input)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel)
    ],
    name="payout_conversation",
    persistent=False
)

# Register the handlers
def register_payout_handlers(app):
    app.add_handler(payout_conversation)