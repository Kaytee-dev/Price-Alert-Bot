import logging
from config import REFERRALS_FILE, BOT_NAME, BOT_LOGS_ID, REFERRAL_PERCENTAGE
from utils import load_json, save_json, build_custom_update_from_query, send_message
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ConversationHandler, 
    MessageHandler, filters, ContextTypes
)

from telegram.constants import ChatAction

import asyncio

# States for the wallet address conversation
ENTERING_WALLET = 1

# Global dictionary to store referral data in-memory
REFERRAL_DATA = {}  # {user_id: {referred_users: [], total_commission: 0.0, ...}}

def load_referral_data():
    global REFERRAL_DATA
    REFERRAL_DATA = load_json(REFERRALS_FILE, {}, "referral data")

def save_referral_data():
    save_json(REFERRALS_FILE, REFERRAL_DATA, "referral data")

def get_user_referral_data(user_id: int) -> Dict:
    user_id_str = str(user_id)
    if user_id_str not in REFERRAL_DATA:
        REFERRAL_DATA[user_id_str] = {
            "referred_users": [],
            "total_commission": 0.0,
            "total_paid": 0.0,
            "wallet_address": "",
            "successful_referrals": 0  # Count of referrals who upgraded for 6+ months
        }
        save_referral_data()
    return REFERRAL_DATA[user_id_str]

def register_referral(referrer_id: int, referred_id: int) -> bool:
    referrer_id_str = str(referrer_id)
    referred_id_str = str(referred_id)
    
    # Initialize referrer data if not exists
    if referrer_id_str not in REFERRAL_DATA:
        REFERRAL_DATA[referrer_id_str] = {
            "referred_users": [],
            "total_commission": 0.0,
            "total_paid": 0.0,
            "wallet_address": "",
            "successful_referrals": 0
        }
    
    # Add referred user if not already referred
    if referred_id_str not in REFERRAL_DATA[referrer_id_str]["referred_users"]:
        REFERRAL_DATA[referrer_id_str]["referred_users"].append(referred_id_str)
        save_referral_data()
        return True
    return False

def handle_successful_referral_upgrade(referrer_id: int, upgrade_fee: float) -> float:
    referrer_id_str = str(referrer_id)
    
    if referrer_id_str in REFERRAL_DATA:
        # Calculate 5% commission
        commission = upgrade_fee * REFERRAL_PERCENTAGE
        
        # Update referrer's data
        REFERRAL_DATA[referrer_id_str]["total_commission"] += commission
        REFERRAL_DATA[referrer_id_str]["successful_referrals"] += 1
        save_referral_data()
        
        return commission
    return 0

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
    
    referral_page_para_1 = (
        "💰 Invite your friends to save 10% on fees. "
        "If you've traded more than $10k volume in a week you'll receive a 35% share of the fees paid by your referrees! "
        "Otherwise, you'll receive a 25% share."
    )

    referral_page_para_2 = (
        "Rewards are paid daily and airdropped directly to your chosen Rewards Wallet. "
        "You must have accrued at least 0.005 SOL in unpaid fees to be eligible for a payout. \n\n"
        "We've established a tiered referral system, ensuring that as more individuals come onboard, rewards extend through five different layers of users. "
        "This structure not only benefits community growth but also significantly "
        "increases the percentage share of fees for everyone.\n\n"
        "Stay tuned for more details on how we'll reward active users and happy trading!"
    )
    # Create the message
    message = (
        f"\n\n🔗 *{BOT_NAME} Referral Program*\n\n"
        f"{referral_page_para_1}\n\n"
        f"📊 *Your Referral Statistics*\n\n"
        f"👤 Total Referrals: {len(user_data['referred_users'])}\n"
        f"✅ Successful Referrals: {user_data['successful_referrals']}\n"
        f"💵 Total Commission: ${user_data['total_commission']:.2f}\n"
        f"💵 Paid: ${user_data['total_paid']:.2f}\n"
        f"💵 Unpaid: ${unpaid_commission:.2f}\n\n"
        f"{referral_page_para_2}\n\n"
        f"Your referral link:\n`{referral_link}`\n\n"
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
        "Please enter your preffered wallet address for receiving referral payouts.\n\n"
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
    wallet_address = update.message.text.strip()
    
    # Basic validation (can be enhanced for specific wallet types)
    if len(wallet_address) < 10:
        await update.message.reply_text(
            "❌ This doesn't appear to be a valid wallet address. Please try again with a valid address."
        )
        return ENTERING_WALLET
    
    # Save the wallet address
    user_id_str = str(user_id)
    REFERRAL_DATA[user_id_str]["wallet_address"] = wallet_address
    save_referral_data()
    
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
            "Our team will process your request within 48 hours."
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
                success = register_referral(referrer_id, user_id)
                
                if success:
                    context.user_data["referred_by"] = referrer_id
                    logging.info(f"User {user_id} was referred by {referrer_id}")

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
                    logging.info(f"User {user_id} was referred by {referrer_id}")
            
        except (ValueError, IndexError):
            pass  # Invalid referral parameter
    

# Function to integrate with your existing upgrade completion
def on_upgrade_completed(user_id: int, upgrade_fee: float, duration_months: int) -> tuple:
    # Find which user referred this user
    referred_by = None
    user_id_str = str(user_id)
    
    for potential_referrer_id, data in REFERRAL_DATA.items():
        if user_id_str in data["referred_users"]:
            referred_by = int(potential_referrer_id)
            break
    
    if referred_by and duration_months >= 6:
        # Process commission for the referrer
        commission = handle_successful_referral_upgrade(referred_by, upgrade_fee)
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
    load_referral_data()

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
    
    # You'll need to modify your existing start handler to incorporate referral functionality
    # or add a new one that works alongside your existing handler
    # application.add_handler(CommandHandler("start", start_with_referral))