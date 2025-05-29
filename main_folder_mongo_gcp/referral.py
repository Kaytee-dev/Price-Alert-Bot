import logging
from config import BOT_NAME, REFERRAL_PERCENTAGE
from util.utils import build_custom_update_from_query, send_message
from typing import Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler, 
    MessageHandler, filters, ContextTypes
)

from telegram.constants import ChatAction
import storage.user_collection as user_collection

import asyncio

logger = logging.getLogger(__name__)

# States for the wallet address conversation
ENTERING_WALLET = 1


def get_user_referral_data(user_id: int) -> Dict:
    user_id_str = str(user_id)
    user_doc = user_collection.USER_COLLECTION.setdefault(user_id_str, {})
    if "referral" not in user_doc:
        user_doc["referral"] = {
            "referred_users": [],
            "total_commission": 0.0,
            "total_paid": 0.0,
            "wallet_address": "",
            "successful_referrals": 0,
            "total_referred": 0
        }
    return user_doc["referral"]


async def register_referral(referrer_id: int, referred_id: int) -> bool:
    referrer_id_str = str(referrer_id)
    referred_id_str = str(referred_id)

    referral_data = get_user_referral_data(referrer_id)
    if referred_id_str not in referral_data["referred_users"]:
        referral_data["referred_users"].append(referred_id_str)
        referral_data.setdefault("total_referred", 0)
        referral_data["total_referred"] += 1

        await user_collection.update_user_fields(referrer_id_str, {
            "referral.referred_users": referral_data["referred_users"],
            "referral.total_referred": referral_data["total_referred"]
        })
        return True
    return False


async def handle_successful_referral_upgrade(referrer_id: int, upgrade_fee: float) -> float:
    referrer_id_str = str(referrer_id)
    referral_data = get_user_referral_data(referrer_id)
    
    commission = upgrade_fee * REFERRAL_PERCENTAGE

    referral_data["total_commission"] += commission
    referral_data["successful_referrals"] += 1

    await user_collection.update_user_fields(referrer_id_str, {
        "referral.total_commission": referral_data["total_commission"],
        "referral.successful_referrals": referral_data["successful_referrals"]
    })
    return commission

# Main referral page handler
async def show_referral_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🔥 Smart user ID detection
    if hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    else:
        user_id = update.effective_chat.id

    # Get user's referral data
    user_data = get_user_referral_data(str(user_id))  # Ensure user_id is string if needed by your storage

    
    # Create bot referral link
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    
    # Calculate unpaid commission
    unpaid_commission = user_data["total_commission"] - user_data["total_paid"]
    
    # Calculate total referred users (historical) - this is successful_referrals + current pending referrals
    total_historical_referrals = user_data.get("total_referred", 0)
    referral_page_para_1 = (
        "💰 Invite your friends and get a 5% referral commision when they upgrade their " 
        "tier to any package with a minimum of 6 months duration. There is no maximum "
        "amount of referral, the more you refer the more your rewards."
    )

    referral_page_para_2 = (
        "Rewards are paid once in a month and to be qualified for referral commission "
        "payout you must have *5 successful referrals* and must have linked your " \
        "*USDC wallet address on Solana network*.\n\nFailure to link your wallet " \
        "address means you will have to wait till the next payout round to receive" \
        "your commission.\n\n" \
        "Also if we need to create a token account for your provided wallet then the fee to create it will " \
        "be deducted from your payout *(~0.3$)*."
    )
    # Create the message
    message = (
        f"\n\n🔗 *{BOT_NAME} Referral Program*\n\n"
        f"{referral_page_para_1}\n\n"
        f"📊 *Your Referral Statistics*\n\n"
        f"👤 Total Referrals (All-time): {total_historical_referrals}\n"
        f"👤 Current Pending Referrals: {len(user_data['referred_users'])}\n"
        f"✅ Successful Referrals: {user_data['successful_referrals']}\n\n"
        f"💵 Total Commission: ${user_data['total_commission']:.2f}\n"
        f"💵 Paid: ${user_data['total_paid']:.2f}\n"
        f"💵 Unpaid: ${unpaid_commission:.2f}\n\n"
        f"{referral_page_para_2}\n\n"
        f"*Your referral link:*\n`{referral_link}`\n\n"
    )
    
    # Add wallet info if available
    if user_data["wallet_address"]:
        # Show only first 6 and last 4 characters of the wallet
        wallet = user_data["wallet_address"]
        masked_wallet = f"{wallet[:6]}...{wallet[-4:]}"
        wallet_text = f"🔑 Wallet: {masked_wallet}"
    else:
        wallet_text = "🔑 No wallet address set"
    
    message += wallet_text
    
    # Create keyboard
    keyboard = [
        [InlineKeyboardButton("💰 Set/Update Wallet Address", callback_data="set_wallet")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_to_dashboard")]
    ]
    
    # Add payout request button if eligible
    if unpaid_commission > 0 and user_data["successful_referrals"] >= 5:
        keyboard.insert(0, [InlineKeyboardButton("💵 Request Payout", callback_data="request_payout")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 🔥 Smart output to callback or normal message
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    return ConversationHandler.END

# Handle wallet address setup
async def prompt_for_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    
    message = (
        "💼 *Set Your Payout Wallet*\n\n"
        "Please enter your *USDC wallet address on Solana network* "
        "preferrably from non-custodial platform like Phantom "
        "for receiving referral payouts.\n\n"
        "Type your wallet address in the next message:"
    )
    
    await update.callback_query.edit_message_text(
        text=message,
        parse_mode='Markdown'
    )
    
    return ENTERING_WALLET

# Handle wallet address input
async def save_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    wallet_address = update.message.text.strip()
    
    # Basic validation (can be enhanced for specific wallet types)
    if len(wallet_address) < 10:
        await update.message.reply_text(
            "❌ This doesn't appear to be a valid wallet address. Please try again with a valid address."
        )
        return ENTERING_WALLET
    
    # Update in-memory cache
    referral_data = user_collection.USER_COLLECTION.setdefault(user_id_str, {}).setdefault("referral", {})
    referral_data["wallet_address"] = wallet_address

    # Update DB
    await user_collection.update_user_fields(user_id_str, {
        "referral.wallet_address": wallet_address
    })
    
    await update.message.reply_text(
        "✅ Your wallet address has been saved successfully!"
    )
    chat_id = update.effective_chat.id

    # 📝 Show 'typing...' animation
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(2)  # wait 2 seconds
    
    # Return to referral dashboard
    return await show_referral_page(update, context)

# Handle payout request
async def request_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_referral_data(user_id)
    
    # Calculate unpaid commission
    unpaid_commission = user_data["total_commission"] - user_data["total_paid"]
    
    # Check eligibility
    if unpaid_commission <= 0:
        message = "❌ You don't have any unpaid commission to request."
    elif user_data["successful_referrals"] < 5:
        message = "❌ You need at least 5 successful referrals to request a payout."
    elif not user_data["wallet_address"]:
        message = "❌ Please set a wallet address before requesting a payout."
    else:
        # In a real implementation, you'd process the payout or notify admins
        message = (
            "✅ Your payout request has been submitted!\n\n"
            f"Amount: ${unpaid_commission:.2f}\n"
            "Thanks for submitting your payout request, it " \
            "has been recorded and will be processed along with other payouts " \
            "as at when due.\n\n" \
            f"Thanks for being a part of *{BOT_NAME}* valuable community."
        )
        
        # Here you could add admin notification logic or automatic payouts
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text=message,
        parse_mode='Markdown'
    )
    
    # Add a button to go back to referral dashboard
    keyboard = [[InlineKeyboardButton("🔙 Back to Referral Dashboard", callback_data="show_referral")]]
    await update.callback_query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return ConversationHandler.END

# Handle /start command with referral parameter
async def start_with_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = (getattr(update, 'effective_user', None) or update.effective_chat).id
    
    # Check if this is a referral start
    if context.args and context.args[0].startswith("ref"):
        try:
            referrer_id = int(context.args[0][3:])  # Extract referrer ID
            
            # Don't allow self-referrals
            if referrer_id != user_id:
                # Register the referral
                success = await register_referral(referrer_id, user_id)
                
                if success:
                    context.user_data["referred_by"] = referrer_id
                    logger.info(f"User {user_id} was referred by {referrer_id}")

                    # Get referrer name
                    referrer = await context.bot.get_chat(referrer_id)
                    referrer_name = referrer.full_name or f"User {referrer_id}"

                    # Get new user's name
                    new_user_name = (getattr(update, 'effective_user', None) or update.effective_chat).full_name or f"User {user_id}"

                    # Notify the referrer
                    await send_message(
                        context.bot,
                        f"🎉 {new_user_name} just joined *{BOT_NAME}* using your referral link! Keep referring to earn more rewards.",
                        chat_id=referrer_id
                    )

                    # Welcome message to referred user
                    await update.message.reply_text(
                        f"🎉 Welcome to *{BOT_NAME}* {new_user_name},\n\nYou were referred by *{referrer_name}*.\n\nUpgrade your account to unlock access to track more token.\n\n With your current *Apprentice tier* you can track up to 3 tokens",
                        parse_mode="Markdown"
                    )

                    # Log the referral
                    logger.info(f"User {user_id} was referred by {referrer_id}")
            
        except (ValueError, IndexError):
            pass  # Invalid referral parameter
    

# Function to integrate with your existing upgrade completion
async def on_upgrade_completed(user_id: int, upgrade_fee: float, duration_months: int) -> tuple:
    referred_by = None
    user_id_str = str(user_id)
    
    for potential_referrer_id, doc in user_collection.USER_COLLECTION.items():
        referral_info = doc.get("referral", {})
        referred_users = referral_info.get("referred_users", [])
        if user_id_str in referred_users:
            referred_by = int(potential_referrer_id)
            break

    if referred_by and duration_months >= 6:
        commission = await handle_successful_referral_upgrade(referred_by, upgrade_fee)

        referred_by_str = str(referred_by)
        referral_info = user_collection.USER_COLLECTION.setdefault(referred_by_str, {}).setdefault("referral", {})

        if user_id_str in referral_info.get("referred_users", []):
            referral_info["referred_users"].remove(user_id_str)

        await user_collection.update_user_fields(referred_by_str, {
            "referral": referral_info
        })

        return True, commission, referred_by

    return False, 0, None


# Modify handle_back_to_dashboard to work with referral module
async def handle_back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    launch_func = context.bot_data.get("launch_dashboard")
    if launch_func:
        custom_update = build_custom_update_from_query(update.callback_query)
        return await launch_func(custom_update, context)
    else:
        await update.callback_query.edit_message_text("⚠️ Dashboard not available.")

# Initialize module
def init_referral_module():
    logger.info("✅ Referral module is ready (MongoDB-backed)")

# Create conversation handler for wallet address setup
wallet_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(prompt_for_wallet, pattern="^set_wallet$")
    ],
    states={
        ENTERING_WALLET: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_wallet_address)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", show_referral_page),
        CallbackQueryHandler(show_referral_page, pattern="^show_referral$")
    ],
    name="wallet_conversation",
    persistent=False
)

# Handlers to add to your application dispatcher
def register_referral_handlers(app):
    # Initialize the module
    init_referral_module()
    
    # Main referral handlers
    app.add_handler(CommandHandler("referral", show_referral_page))
    app.add_handler(CallbackQueryHandler(show_referral_page, pattern="^show_referral$"))
    app.add_handler(CallbackQueryHandler(handle_back_to_dashboard, pattern="^back_to_dashboard$"))
    
    # Wallet setup handlers
    app.add_handler(wallet_conv_handler)
    
    # Payout request handler
    app.add_handler(CallbackQueryHandler(request_payout, pattern="^request_payout$"))
    