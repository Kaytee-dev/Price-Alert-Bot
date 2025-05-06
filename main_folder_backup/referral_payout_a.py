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
from config import SOLSCAN_BASE, SOLSCAN_TX_BASE, SOLANA_RPC
from util.process_single_payout_util import process_single_payout

# Constants
MIN_PAYOUT_THRESHOLD = 0.005  # Minimum payout in SOL
NETWORK_FEE_PER_TX = 0.000005  # SOL fee per transaction
MIN_SUCCESSFUL_REFERRALS = 5  # Minimum successful referrals to be eligible

# States for the payout conversation
CONFIRM_PAYOUT, ENTER_WALLET_KEY = range(2)

# Determine if we're on mainnet or devnet
IS_MAINNET = "mainnet" in SOLANA_RPC.lower()
CLUSTER = "mainnet" if IS_MAINNET else "devnet"

# Filter eligible users for payout
def get_eligible_users() -> List[Tuple[str, Dict[str, Any]]]:
    eligible_users = []
    
    for user_id, data in referral.REFERRAL_DATA.items():
        # Calculate unpaid commission
        unpaid_commission = data["total_commission"] - data["total_paid"]
        
        # Check eligibility criteria
        if (unpaid_commission > 0 and 
            data["successful_referrals"] >= MIN_SUCCESSFUL_REFERRALS and
            data["wallet_address"]):
            eligible_users.append((user_id, data))
    
    return eligible_users

# Validate wallet addresses
async def validate_wallet_addresses(eligible_users: List[Tuple[str, Dict[str, Any]]]) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, str]]]:
    valid_users = []
    invalid_users = []
    
    for user_id, data in eligible_users:
        addr = data["wallet_address"]
        
        # Format check
        if not (32 <= len(addr) <= 44):
            invalid_users.append((user_id, "Invalid wallet format"))
            continue
        
        try:
            # Try to create a Pubkey to validate the address
            _ = Pubkey.from_string(addr)
        except Exception:
            invalid_users.append((user_id, "Invalid base58 public key"))
            continue
        
        try:
            # Check if wallet exists on Solscan
            url = SOLSCAN_BASE.format(addr)
            resp = requests.get(url, timeout=5)
            if resp.status_code != 404:
                valid_users.append((user_id, data))
            else:
                invalid_users.append((user_id, "Wallet not indexed on Solscan"))
        except Exception as e:
            invalid_users.append((user_id, f"Validation error: {str(e)}"))
    
    return valid_users, invalid_users


async def calculate_payout_totals(valid_users: List[Tuple[str, Dict[str, Any]]]) -> Tuple[int, float, float, float]:
    total_users = len(valid_users)
    total_commission_usd = sum(data["total_commission"] - data["total_paid"] for _, data in valid_users)
    sol_usd_price = await fetch_sol_price_usd()
    network_fee_base = NETWORK_FEE_PER_TX * sol_usd_price
    network_fees = total_users * network_fee_base
    network_fees_sol = network_fees / sol_usd_price
    total_cost = total_commission_usd + network_fees  # No conversion to SOL

    return total_users, total_commission_usd, network_fees, network_fees_sol, total_cost


# Main command handler
@restricted_to_admin
async def process_referral_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Load the latest referral data
    referral.REFERRAL_DATA
    
    # Get eligible users
    eligible_users = get_eligible_users()
    
    if not eligible_users:
        await update.message.reply_text(
            "❌ No users currently meet the payout criteria.\n\n"
            f"Requirements:\n"
            f"- Minimum {MIN_SUCCESSFUL_REFERRALS} successful referrals\n"
            f"- Unpaid commission > 0\n"
            f"- Valid wallet address set"
        )
        return ConversationHandler.END
    
    # Show processing message
    processing_msg = await update.message.reply_text(
        "⏳ Validating wallet addresses, please wait..."
    )
    
    # Get chat ID for showing typing indicator
    chat_id = update.effective_chat.id
    
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    # Validate wallet addresses
    valid_users, invalid_users = await validate_wallet_addresses(eligible_users)
    
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
        # f"💰 Total Commission (SOL): {total_sol:.6f} SOL\n"
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
        f"⏳ Processing {len(valid_users)} payments...\n"
        "0% complete (0/{len(valid_users)})"
    )
    
    successful_transfers = []
    failed_transfers = []
    
    # Process each payment
    for i, (user_id, data) in enumerate(valid_users):
        # Calculate unpaid commission
        unpaid_commission = data["total_commission"] - data["total_paid"]
        amount_usd = unpaid_commission
        wallet_address = data["wallet_address"]
        
        # Update processing message with progress
        if i % 5 == 0 or i == len(valid_users) - 1:  # Update every 5 transactions or on the last one
            progress = int((i / len(valid_users)) * 100)
            await processing_msg.edit_text(
                f"⏳ Processing payments... {progress}% complete ({i}/{len(valid_users)})"
            )
        
        # Process the actual payment
        success, tx_sig, message = await process_single_payout(
            user_id, wallet_address, amount_usd, keypair, context
        )
        
        if success:
            # Update referral data
            referral.REFERRAL_DATA[user_id]["total_paid"] += unpaid_commission
            referral.REFERRAL_DATA[user_id]["successful_referrals"] = 0  # Reset successful referrals
            referral.REFERRAL_DATA[user_id]["tx_sig"] = tx_sig  # Store transaction signature
            
            
            successful_transfers.append((user_id, amount_usd, tx_sig))
        else:
            failed_transfers.append((user_id, amount_usd, message))
    
    # Save updated referral data
    referral.save_referral_data()
    
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
            # # Convert to USD for the message
            # amount_usd = amount_sol * SOL_TO_USD_RATE
            
            message = (
                "💰 *Referral Commission Payout Received!*\n\n"
                f"You've received a referral commission payout of *${amount_usd:.2f}* .\n\n"
                f"Transaction: [View on Solscan]({SOLSCAN_TX_BASE.format(tx_sig)})\n\n"
                "Thanks for being a valuable part of our community! Continue referring users to earn more rewards."
            )
            
            await context.bot.send_message(
                chat_id=int(user_id),
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            logging.error(f"Failed to notify user {user_id} about payout: {str(e)}")

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
        CONFIRM_PAYOUT: [
            CallbackQueryHandler(handle_confirm_payout, pattern="^confirm_payout$|^cancel_payout$")
        ],
        ENTER_WALLET_KEY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_key_input)
        ]
        # PROCESSING_PAYOUTS: [
        #     # This state is handled internally by process_payments
        # ]
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