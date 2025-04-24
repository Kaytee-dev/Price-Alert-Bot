import asyncio

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler

import storage.users as users
import storage.history as history
import storage.tiers as tiers

from datetime import datetime, timedelta
import urllib.parse

from utils import CustomUpdate, CustomEffectiveChat, CustomMessage, build_custom_update_from_query


# At the top of your file
SELECTING_TIER, SELECTING_DURATION, PAYMENT, VERIFICATION = range(4)

async def launch(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    msg = (
        f"*Welcome To PumpCycle Bot*\n\n"
        f"Tracks tokens that cooled off but still have holders. Alerts you when they’re warming up for Round 2. 🔥📈\n\n"
        f"{monitor_state}\n"
        f"🎯 Tier: {user_tier.capitalize()} ({user_limit} token limit)\n\n"
        f"👤 You are tracking {len(user_tokens)} token(s).\n"
        f"🌐 Total unique tokens tracked: {len(all_tokens)}\n\n"
        f"💥 Active spikes (≥15%): {spike_count}\n"
        f"🕓 Last update: {last_update if last_update else 'N/A'}"
    )


    keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("✅ Start Tracking", callback_data="cmd_start"),
        InlineKeyboardButton("🛑 Stop Tracking", callback_data="cmd_stop")
    ],
    [
        InlineKeyboardButton("🔄 Reset Tracking List", callback_data="cmd_reset"),
        InlineKeyboardButton("📋 List Tracked Tokens", callback_data="cmd_list")
    ],
    [
        InlineKeyboardButton("📊 Tracking Status", callback_data="cmd_status"),
        InlineKeyboardButton("❓ Help", callback_data="cmd_help")
    ],
    [
        InlineKeyboardButton("⭐ Upgrade", callback_data="cmd_upgrade")
    ],
    ])

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)



async def start_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the upgrade process and ask user to select a tier."""
    # Get user data
    query = update.callback_query
    if query:  # Started from a button
        await query.answer()
        chat_id = str(query.message.chat_id)
        message = query.message
    else:  # Started from a command
        chat_id = str(update.effective_chat.id)
        message = update.message
    
    user_id = int(chat_id)
    current_tier = tiers.get_user_tier(user_id)
    
    # Store the original message if we need to return to dashboard
    if hasattr(update, 'callback_query') and update.callback_query:
        context.user_data['dashboard_message'] = update.callback_query.message
    
    # Create tier options
    tier_options = []
    if current_tier != "Disciple":
        tier_options.append(InlineKeyboardButton("🛡️ Disciple", callback_data="tier_disciple"))
    if current_tier != "Chieftain":
        tier_options.append(InlineKeyboardButton("👑 Chieftain", callback_data="tier_chieftain"))
    if current_tier != "Overlord":
        tier_options.append(InlineKeyboardButton("🕶️ Overlord", callback_data="tier_overlord"))
    
    
    # Add a cancel button
    tier_options.append(InlineKeyboardButton("🔙 Cancel", callback_data="cancel"))
    
    keyboard = InlineKeyboardMarkup([[btn] for btn in tier_options])
    
    msg = (
        f"⭐ *Upgrade your Tier*\n\n"
        f"Your current tier: {current_tier.capitalize()}\n\n"
        f"Select a tier to upgrade to:"
    )
    
    if query:
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    
    return SELECTING_TIER

async def select_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle tier selection and ask for duration."""
    query = update.callback_query
    await query.answer()
    
    # Extract selected tier and store it
    selected_tier = query.data.split("_")[1]
    context.user_data['selected_tier'] = selected_tier
    
    # Create duration keyboard
    duration_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗓️ 1 Month", callback_data="duration_1"),
         InlineKeyboardButton("🗓️ 6 Months", callback_data="duration_6")
        ],

        [InlineKeyboardButton("🗓️ 1 Year", callback_data="duration_12")],

        [InlineKeyboardButton("🔙 Back", callback_data="back"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ]
    ])
    
    # Show pricing information
    prices = {
        "disciple": {"1": "10 SOL", "6": "50 SOL", "12": "90 SOL"},
        "chieftain": {"1": "20 SOL", "6": "100 SOL", "12": "180 SOL"},
        "overlord": {"1": "30 SOL", "6": "120 SOL", "12": "280 SOL"}
    }
    
    msg = (
        f"⭐ *{selected_tier.capitalize()} Tier*\n\n"
        f"Select subscription duration:\n\n"
        f"🗓️ 1 Month: {prices[selected_tier]['1']}\n"
        f"🗓️ 6 Months: {prices[selected_tier]['6']}\n"
        f"🗓️ 1 Year: {prices[selected_tier]['12']}"
    )
    
    await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=duration_keyboard)
    return SELECTING_DURATION

# Continue with handlers for other states...
async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle duration selection and show payment options."""
    query = update.callback_query
    await query.answer()
    
    # Extract and store selected duration
    duration_months = query.data.split("_")[1]
    context.user_data['duration'] = duration_months
    selected_tier = context.user_data['selected_tier']
    
    # Generate payment information
    amount = {
        "disciple": {"1": 10, "6": 50, "12": 90},
        "chieftain": {"1": 20, "6": 100, "12": 180},
        "overlord": {"1": 40, "6": 120, "12": 280}
    }
    
    # Generate Solana Pay link
    user_id = str(query.message.chat_id)
    payment_amount = amount[selected_tier][duration_months]
    payment_reference = f"test_{user_id}_{selected_tier}_{duration_months}" # test_ for testing sake
    payment_label = f"Upgrade to {selected_tier.capitalize()} for {duration_months} month(s)"
    
    # Store payment info for verification
    context.user_data['payment_amount'] = payment_amount
    context.user_data['payment_reference'] = payment_reference
    
    # Generate the payment link (implement this function)
    payment_link = generate_solana_payment_link(
        amount=payment_amount,
        reference=payment_reference,
        label=payment_label
    )
    
    # Create payment keyboard
    payment_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Pay with Solana", url=payment_link)],

        [InlineKeyboardButton("✅ I've Paid", callback_data="verify"),
         InlineKeyboardButton("🔙 Back", callback_data="back"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ]
    ])
    
    msg = (
        f"💰 *Payment*\n\n"
        f"Upgrade to {selected_tier.capitalize()} tier for {duration_months} month(s)\n"
        f"Amount: {payment_amount} SOL\n\n"
        f"Click the button below to pay with Solana Pay. After payment, click 'I've Paid' to verify."
    )
    
    await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=payment_keyboard)
    return PAYMENT

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify the payment and update user status if successful."""
    query = update.callback_query
    await query.answer()
    
    # Get payment details from context
    user_id = int(query.message.chat_id)
    selected_tier = context.user_data['selected_tier']
    duration_months = context.user_data['duration']
    payment_reference = context.user_data['payment_reference']
    
    # Show checking message
    await query.message.edit_text(
        "⏳ Checking payment status...",
        parse_mode="Markdown"
    )
    
    # Implement the payment verification logic
    payment_verified = await check_blockchain_for_payment(payment_reference)
    
    if payment_verified:
        # Update user's tier in your system
        await tiers.set_user_tier(user_id, selected_tier)
        
        # Calculate and store subscription expiry
        expiry_date = datetime.now() + timedelta(days=int(duration_months) * 30)
        tiers.set_user_expiry(user_id, expiry_date)
        
        # Create dashboard button
        complete_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Back to Dashboard", callback_data="complete")]
        ])
        
        msg = (
            f"✅ *Upgrade Successful!*\n\n"
            f"You have been upgraded to {selected_tier.capitalize()} tier for {duration_months} month(s).\n"
            f"Your subscription will expire on: {expiry_date.strftime('%d %b %Y')}\n\n"
            f"Enjoy your new features and increased limits!"
        )
        
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=complete_keyboard)
        return VERIFICATION
    else:
        # Payment not found
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄Try Again", callback_data="retry")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        
        msg = (
            f"❌ *Payment Not Verified*\n\n"
            f"We couldn't verify your payment. Please ensure you've completed the payment and try again."
        )
        
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=retry_keyboard)
        return PAYMENT

async def complete_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End the conversation and go back to dashboard."""
    query = update.callback_query
    await query.answer()
    
    # Return to dashboard
    # custom_chat = CustomEffectiveChat(id=int(query.message.chat_id))
    # custom_message = CustomMessage(chat_id=int(query.message.chat_id))
    custom_update = build_custom_update_from_query(query)
    await launch(custom_update, context)
    
    # Clear user data
    context.user_data.clear()
    return ConversationHandler.END

async def retry_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retry payment verification."""
    return await verify_payment(update, context)

async def back_to_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to tier selection."""
    query = update.callback_query
    await query.answer()
    return await start_upgrade(update, context)

async def back_to_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to duration selection."""
    query = update.callback_query
    await query.answer()
    
    # Re-trigger duration selection with the stored tier
    class CustomCallbackQuery:
        def __init__(self, original_query, data):
            self.message = original_query.message
            self.data = data
            self.answer = original_query.answer
    
    # Create a fake callback query with the tier data
    selected_tier = context.user_data['selected_tier']
    fake_query = CustomCallbackQuery(query, f"tier_{selected_tier}")
    update.callback_query = fake_query
    
    return await select_duration(update, context)


def generate_solana_payment_link(amount, reference, label):
    # Create a Solana Pay link
    # This is a simplified example - you'll need to implement this based on Solana Pay docs
    recipient = "YOUR_SOLANA_WALLET_ADDRESS"
    encoded_label = urllib.parse.quote(label)
    encoded_reference = urllib.parse.quote(reference)
    
    #return f"solana:{recipient}?amount={amount}&reference={encoded_reference}&label={encoded_label}"
    return f"https://example.com/pay?amount={amount}&ref={encoded_reference}&label={encoded_label}"


async def check_blockchain_for_payment(reference: str) -> bool:
    """
    Mock payment verification on Solana blockchain.
    Replace this with actual logic using Solana Pay or Solana JSON-RPC.
    
    Args:
        reference (str): Unique reference string used in the payment link.
    
    Returns:
        bool: True if payment is verified, False otherwise.
    """
    # Allow all test_* references for testing flow
    if reference.startswith("test_"):
        return True

    # Example: delay & fail others (simulate processing
    await asyncio.sleep(1)
    return False


async def cancel_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the upgrade process and return to dashboard."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        # Clear any stored user data for the upgrade flow
        context.user_data.clear()
        
        # Return to dashboard using your existing launch function
        # custom_chat = CustomEffectiveChat(id=int(query.message.chat_id))
        # custom_message = CustomMessage(chat_id=int(query.message.chat_id))

        custom_update = build_custom_update_from_query(query)
        await launch(custom_update, context)
    else:
        # If triggered by command instead of button
        await update.message.reply_text("Upgrade canceled. Use /lc to return to main menu.")
    
    return ConversationHandler.END

upgrade_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("upgrade", start_upgrade),
            CallbackQueryHandler(start_upgrade, pattern="^cmd_upgrade$")
        ],
        states={
            SELECTING_TIER: [
                CallbackQueryHandler(select_duration, pattern="^tier_"),
                CallbackQueryHandler(cancel_upgrade, pattern="^cancel$")
            ],
            SELECTING_DURATION: [
                CallbackQueryHandler(handle_payment, pattern="^duration_"),
                CallbackQueryHandler(back_to_tier, pattern="^back$")
            ],
            PAYMENT: [
                CallbackQueryHandler(verify_payment, pattern="^verify$"),
                CallbackQueryHandler(back_to_duration, pattern="^back$")
            ],
            VERIFICATION: [
                CallbackQueryHandler(complete_upgrade, pattern="^complete$"),
                CallbackQueryHandler(retry_verification, pattern="^retry$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_upgrade),
            CallbackQueryHandler(cancel_upgrade, pattern="^cancel$")
        ],
        name="upgrade_conversation",
        persistent=False
    )

