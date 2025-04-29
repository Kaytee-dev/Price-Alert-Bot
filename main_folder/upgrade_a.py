import asyncio

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler

import storage.users as users
import storage.history as history
import storage.tiers as tiers

from datetime import datetime, timedelta
import urllib.parse

from utils import CustomUpdate, CustomEffectiveChat, CustomMessage, build_custom_update_from_query, send_message
from config import SUPER_ADMIN_ID, BOT_LOGS_ID

from referral import on_upgrade_completed


# At the top of your file
SELECTING_TIER, SELECTING_DURATION, PAYMENT, VERIFICATION = range(4)

async def go_back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    launch_func = context.bot_data.get("launch_dashboard")
    if launch_func:
        custom_update = build_custom_update_from_query(update.callback_query)
        return await launch_func(custom_update, context)
    else:
        await update.callback_query.edit_message_text("⚠️ Dashboard unavailable.")


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

    # Create tier options based on current tier
    tier_options = []

    if current_tier == "apprentice":
        # Show all upgrade options for Apprentice
        tier_options.append(InlineKeyboardButton("🛡️ Disciple", callback_data="tier_disciple"))
        tier_options.append(InlineKeyboardButton("👑 Chieftain", callback_data="tier_chieftain"))
        tier_options.append(InlineKeyboardButton("🕶️ Overlord", callback_data="tier_overlord"))
    elif current_tier == "disciple":
        # Show only Chieftain and Overlord for Disciple
        tier_options.append(InlineKeyboardButton("👑 Chieftain", callback_data="tier_chieftain"))
        tier_options.append(InlineKeyboardButton("🕶️ Overlord", callback_data="tier_overlord"))
    elif current_tier == "chieftain":
        # Show only Overlord for Chieftain
        tier_options.append(InlineKeyboardButton("🕶️ Overlord", callback_data="tier_overlord"))

    # Create keyboard layout
    keyboard = []
    if tier_options:
        if len(tier_options) == 3:
            # For Apprentice: Two columns for first two tiers
            keyboard.append([tier_options[0], tier_options[1]])
            # Highest tier gets full width
            keyboard.append([tier_options[2]])
        elif len(tier_options) == 2:
            # For Disciple: One button per row
            keyboard.append([tier_options[0], tier_options[1]])
            # keyboard.append([tier_options[0]])
            # keyboard.append([tier_options[1]])
        else:
            # For Chieftain: Just one button
            keyboard.append([tier_options[0]])
        
        # Add the cancel button (full width)
        keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="cancel")])
        
        msg = (
            f"⭐ *Upgrade your Tier*\n\n"
            f"Your current tier: *{current_tier.capitalize()}*\n\n"
            f"Select a tier to upgrade to:\n\n"
            f"🛡️ *Disciple*\n"
            f"🪙 Track up to 10 tokens\n"
            f"🔔 Real time spike alerts\n"
            f"🕓 Around the clock token tracking\n\n"
            f"👑 *Chieftain*\n"
            f"🪙 Track up to 20 tokens\n"
            f"🔔 Real time spike alerts\n"
            f"🕓 Around the clock token tracking\n\n"
            f"🕶️ *Overlord*\n"
            f"🪙 Track up to 40 tokens\n"
            f"🔔 Real time spike alerts\n"
            f"🕓 Around the clock token tracking\n\n"
        )
    else:
        # For Overlord or any other case, display the message about contacting admin
        keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="complete")]]
        
        msg = (
            f"⭐ *Upgrade Information*\n\n"
            f"Your current tier: {current_tier.capitalize()}\n\n"
            f"You've reached the highest tier available. If you need more access to token tracking, "
            f"please [contact an administrator](https://your-contact-link-here)."
        )

    keyboard = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    
    return SELECTING_TIER


async def select_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_tier = query.data.split("_")[1]
    context.user_data['selected_tier'] = selected_tier

    prices = {
        "disciple": {"1": 10, "6": 54, "12": 102},
        "chieftain": {"1": 20, "6": 108, "12": 204},
        "overlord": {"1": 40, "6": 216, "12": 408}
    }

    one_month_price = prices[selected_tier]["1"]
    six_months_price = prices[selected_tier]["6"]
    twelve_months_price = prices[selected_tier]["12"]

    six_months_original = one_month_price * 6
    twelve_months_original = one_month_price * 12

    six_months_saved = six_months_original - six_months_price
    twelve_months_saved = twelve_months_original - twelve_months_price

    # 🏷️ Smarter Button Labels
    duration_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗓️ 1 Month", callback_data="duration_1"),
            InlineKeyboardButton(f"⭐ 6 Months (Save 10%)", callback_data="duration_6")
        ],
        [
            InlineKeyboardButton(f"🔥 1 Year (Save 15%)", callback_data="duration_12")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ]
    ])

   
    msg = (
    f"⭐ <b>{selected_tier.capitalize()} Tier</b>\n\n"
    f"Choose your subscription plan:\n\n"
    f"🗓️ 1 Month: <b>{one_month_price} SOL</b>\n\n"
    f"⭐ 6 Months:\n"
    f"<s>{six_months_original} SOL</s> ➔ <b>{six_months_price} SOL</b>  🏷️ <b>Save {six_months_saved} SOL (10%)</b>\n\n"
    f"🔥 1 Year:\n"
    f"<s>{twelve_months_original} SOL</s> ➔ <b>{twelve_months_price} SOL</b>  🏷️ <b>Save {twelve_months_saved} SOL (15%)</b>\n"
    )

    await query.message.edit_text(msg, parse_mode="HTML", reply_markup=duration_keyboard)
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
        "disciple": {"1": 10, "6": 54, "12": 102},
        "chieftain": {"1": 20, "6": 108, "12": 204},
        "overlord": {"1": 40, "6": 216, "12": 408}
    }
    
    # Generate Solana Pay link
    user_id = str(query.message.chat_id)
    payment_amount = amount[selected_tier][duration_months]
    payment_reference = f"tt_{user_id}_{selected_tier}_{duration_months}" # test_ for testing sake
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


# async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Verify the payment and update user status if successful."""
#     query = update.callback_query
#     await query.answer()

#     user_id = int(query.message.chat_id)
#     selected_tier = context.user_data['selected_tier']
#     duration_months = context.user_data['duration']
#     payment_reference = context.user_data['payment_reference']

#     # Show checking message
#     await query.message.edit_text(
#         "⏳ Checking payment status...",
#         parse_mode="Markdown"
#     )

#     payment_verified = await check_blockchain_for_payment(payment_reference)

#     if payment_verified:
#         await tiers.set_user_tier(user_id, selected_tier)

#         expiry_date = datetime.now() + timedelta(days=int(duration_months) * 30)
#         tiers.set_user_expiry(user_id, expiry_date)

#         upgrade_fee = context.user_data.get("payment_amount", 0)
#         success, commission, referrer_id = on_upgrade_completed(user_id, upgrade_fee, int(duration_months))

#         if success and referrer_id:
#             # Referral bonus handling
#             referrer = await context.bot.get_chat(referrer_id)
#             referred = await context.bot.get_chat(user_id)

#             referrer_name = referrer.full_name or f"User {referrer_id}"
#             referred_name = referred.full_name or f"User {user_id}"

#             await send_message(
#                 context.bot,
#                 f"🎉 Hey {referrer_name},\n\n You just earned ${commission:.2f} commission from referring {referred_name}!",
#                 chat_id=referrer_id
#             )

#             await send_message(
#                 context.bot,
#                 f"📣 Referral bonus:\n\nReferrer {referrer_name} (ID: `{referrer_id}`) earned ${commission:.2f} commission from referring {referred_name} (ID: `{user_id}`) after upgrading to {selected_tier.capitalize()} for {duration_months} month(s).",
#                 chat_id=BOT_LOGS_ID,
#                 super_admin=SUPER_ADMIN_ID
#             )
#         else:
#             # No referrer; still get referred_name for logs
#             referred = await context.bot.get_chat(user_id)
#             referred_name = referred.full_name or f"User {user_id}"

#         # In both cases, log the upgrade success
#         await send_message(
#             context.bot,
#             f"📢 User {referred_name} (ID: `{user_id}`) has successfully upgraded to *{selected_tier.capitalize()}* tier for {duration_months} month(s).\n\n"
#             f"⏳ Expiry: {expiry_date.strftime('%d %b %Y')} | Ref: `{payment_reference}`",
#             chat_id=BOT_LOGS_ID,
#             super_admin=SUPER_ADMIN_ID
#         )

#         complete_keyboard = InlineKeyboardMarkup([
#             [InlineKeyboardButton("🏠 Back to Dashboard", callback_data="complete")]
#         ])

#         success_msg = (
#             f"✅ *Upgrade Successful!*\n\n"
#             f"You have been upgraded to {selected_tier.capitalize()} tier for {duration_months} month(s).\n"
#             f"Your subscription will expire on: {expiry_date.strftime('%d %b %Y')}\n\n"
#             f"Enjoy your new features and increased limits!"
#         )

#         await query.message.edit_text(success_msg, parse_mode="Markdown", reply_markup=complete_keyboard)

#         return VERIFICATION

#     else:
#         # Payment not verified
#         retry_keyboard = InlineKeyboardMarkup([
#             [InlineKeyboardButton("🔄 Try Again", callback_data="retry")],
#             [InlineKeyboardButton("🔙 Back", callback_data="back")]
#         ])

#         fail_msg = (
#             f"❌ *Payment Not Verified*\n\n"
#             f"We couldn't verify your payment. Please ensure you've completed the payment and try again."
#         )

#         await query.message.edit_text(fail_msg, parse_mode="Markdown", reply_markup=retry_keyboard)

#         await send_message(
#             context.bot,
#             f"❌ Payment failed for user `{user_id}`.\nTier: *{selected_tier.capitalize()}* | Ref: `{payment_reference}`",
#             chat_id=BOT_LOGS_ID,
#             super_admin=SUPER_ADMIN_ID
#         )

#         return PAYMENT

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify the payment and update user status if successful."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.message.chat_id)
    selected_tier = context.user_data.get('selected_tier')
    duration_months = context.user_data.get('duration')
    payment_reference = context.user_data.get('payment_reference')

    # Validate critical info
    if not (selected_tier and duration_months and payment_reference):
        await query.message.edit_text(
            "⚠️ Missing necessary information. Please restart with /upgrade.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    try:
        # Always change text slightly to avoid Telegram "no change" errors
        await query.message.edit_text(
            "⏳ Rechecking your payment... Please wait a moment.",
            parse_mode="Markdown"
        )

        # Try payment verification
        payment_verified = await check_blockchain_for_payment(payment_reference)

    except Exception as e:
        await query.message.edit_text(
            f"❌ Internal error during payment verification.\n\nError: `{str(e)}`",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    if payment_verified:
        await tiers.set_user_tier(user_id, selected_tier)
        expiry_date = datetime.now() + timedelta(days=int(duration_months) * 30)
        tiers.set_user_expiry(user_id, expiry_date)

        upgrade_fee = context.user_data.get("payment_amount", 0)
        success, commission, referrer_id = on_upgrade_completed(user_id, upgrade_fee, int(duration_months))

        if success and referrer_id:
            referrer = await context.bot.get_chat(referrer_id)
            referred = await context.bot.get_chat(user_id)

            referrer_name = referrer.full_name or f"User {referrer_id}"
            referred_name = referred.full_name or f"User {user_id}"

            await send_message(
                context.bot,
                f"🎉 Hey {referrer_name},\n\nYou just earned ${commission:.2f} commission from referring {referred_name}!",
                chat_id=referrer_id
            )

            await send_message(
                context.bot,
                f"📣 Referral bonus:\n\nReferrer {referrer_name} (ID: `{referrer_id}`) earned ${commission:.2f} commission from referring {referred_name} (ID: `{user_id}`) after upgrading to {selected_tier.capitalize()} for {duration_months} month(s).",
                chat_id=BOT_LOGS_ID,
                super_admin=SUPER_ADMIN_ID
            )
        else:
            referred = await context.bot.get_chat(user_id)
            referred_name = referred.full_name or f"User {user_id}"

        # Always log successful upgrade
        await send_message(
            context.bot,
            f"📢 User {referred_name} (ID: `{user_id}`) has successfully upgraded to *{selected_tier.capitalize()}* tier for {duration_months} month(s).\n\n"
            f"⏳ Expiry: {expiry_date.strftime('%d %b %Y')} | Ref: `{payment_reference}`",
            chat_id=BOT_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

        complete_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Back to Dashboard", callback_data="complete")]
        ])

        success_msg = (
            f"✅ *Upgrade Successful!*\n\n"
            f"You have been upgraded to {selected_tier.capitalize()} tier for {duration_months} month(s).\n"
            f"Your subscription will expire on: {expiry_date.strftime('%d %b %Y')}.\n\n"
            f"Enjoy your new features and increased limits!"
        )

        await query.message.edit_text(success_msg, parse_mode="Markdown", reply_markup=complete_keyboard)
        return VERIFICATION

    else:
        # Payment not verified
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="retry")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])

        fail_msg = (
            f"❌ *Payment Not Verified*\n\n"
            f"We couldn't verify your payment. Please ensure you've completed the payment and try again."
        )

        await query.message.edit_text(fail_msg, parse_mode="Markdown", reply_markup=retry_keyboard)

        await send_message(
            context.bot,
            f"❌ Payment failed for user `{user_id}`.\nTier: *{selected_tier.capitalize()}* | Ref: `{payment_reference}`",
            chat_id=BOT_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )

        return PAYMENT


async def complete_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End the conversation and go back to dashboard."""
    query = update.callback_query
    await query.answer()
    
    # Return to dashboard
    await go_back_to_dashboard(update, context)
    
    # Clear user data
    context.user_data.clear()
    return ConversationHandler.END

# async def retry_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Retry payment verification safely."""
#     query = update.callback_query
#     await query.answer()

#     # Check required data
#     if not all(k in context.user_data for k in ("payment_reference", "selected_tier", "duration")):
#         await query.message.edit_text(
#             "⚠️ Cannot retry because necessary payment info was lost. Please restart the upgrade process with /upgrade.",
#             parse_mode="Markdown"
#         )
#         return ConversationHandler.END

#     # Safe to retry
#     return await verify_payment(update, context)

async def retry_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retry payment verification safely."""
    query = update.callback_query
    await query.answer()

    # Check required payment reference
    if not context.user_data.get("payment_reference"):
        await query.message.edit_text(
            "⚠️ Missing payment information. Please restart the upgrade process with /upgrade.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Safe to retry
    return await verify_payment(update, context)


async def back_to_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to tier selection."""
    query = update.callback_query
    await query.answer()
    return await start_upgrade(update, context)


async def back_to_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_tier = context.user_data['selected_tier']

    # Simulate a fake CallbackQuery just for the function call
    class CustomCallbackQuery:
        def __init__(self, original_query, data):
            self.message = original_query.message
            self.data = data
            self.answer = original_query.answer

    fake_query = CustomCallbackQuery(query, f"tier_{selected_tier}")

    # Instead of modifying update, directly call select_duration
    return await select_duration(Update(update.update_id, callback_query=fake_query), context)


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
        await go_back_to_dashboard(update, context)
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
                CallbackQueryHandler(complete_upgrade, pattern="^complete$"),
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

