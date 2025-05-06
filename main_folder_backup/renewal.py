import aiohttp
import qrcode
import io
import secrets
import asyncio

from telegram.error import BadRequest
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler,
                         MessageHandler, filters
                         )

import storage.tiers as tiers
import storage.expiry as expiry

from storage import wallets
from storage import payment_logs
from withdrawal import forward_user_payment

from datetime import datetime, timedelta

from util.utils import CustomUpdate, CustomEffectiveChat, CustomMessage, build_custom_update_from_query, send_message
from config import (SUPER_ADMIN_ID, DIVIDER_LINE, BOT_TG_GROUP,
                   SOLANA_RPC, SOL_DECIMALS, SOL_PAYMENT_TOLERANCE,
                   BOT_INFO_LOGS_ID, BOT_REFERRAL_LOGS_ID,
                   BOT_ERROR_LOGS_ID
                   )

from upgrade import fetch_sol_price_usd, go_back_to_dashboard, prompt_transaction_hash
from referral import on_upgrade_completed

# === STATE CONSTANTS ===
SELECTING_DURATION, PAYMENT, ASK_TRANSACTION_HASH, VERIFICATION = range(4)


# async def fetch_sol_price_usd() -> float:
#     """Fetch current SOL price in USD from CoinGecko."""
#     url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
#     async with aiohttp.ClientSession() as session:
#         async with session.get(url) as resp:
#             data = await resp.json()
#             return data['solana']['usd']

# === TRANSACTION HASH PROMPT ===
async def prompt_transaction_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.message.edit_text(
            "🧾 Please paste your transaction hash below (e.g. `5N9zFe...`).",
            parse_mode="Markdown"
        )
    except BadRequest as e:
        if "message to edit" in str(e):
            await query.message.reply_text(
                "🧾 Please paste your transaction hash below (e.g. `5N9zFe...`).",
                parse_mode="Markdown"
            )
        else:
            raise

    return ASK_TRANSACTION_HASH

# async def go_back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     launch_func = context.bot_data.get("launch_dashboard")
#     if launch_func:
#         custom_update = build_custom_update_from_query(update.callback_query)
#         return await launch_func(custom_update, context)
#     else:
#         try:
#             await update.callback_query.edit_message_text("⚠️ Dashboard unavailable.")
#         except BadRequest as e:
#             if "message to edit" in str(e):
#                 await update.effective_chat.send_message("⚠️ Dashboard unavailable.")
#             else:
#                 raise

async def start_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the renewal process and show user's current tier and expiry."""
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
    expiry_date = tiers.get_user_expiry(user_id)
    
    # Store the original message if we need to return to dashboard
    if hasattr(update, 'callback_query') and update.callback_query:
        context.user_data['dashboard_message'] = update.callback_query.message

    # Save current tier for later
    context.user_data['current_tier'] = current_tier

    # Format expiry date
    expiry_str = "Not set"
    if expiry_date:
        if isinstance(expiry_date, str):
            try:
                expiry_date = datetime.fromisoformat(expiry_date)
                expiry_str = expiry_date.strftime("%d %b %Y")
            except ValueError:
                expiry_str = expiry_date
        else:
            expiry_str = expiry_date.strftime("%d %b %Y")

    # Create duration options
    duration_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗓️ 1 Month", callback_data="duration_1"),
            InlineKeyboardButton("⭐ 6 Months", callback_data="duration_6")
        ],
        [
            InlineKeyboardButton("🔥 1 Year", callback_data="duration_12")
        ],
        [
            InlineKeyboardButton("🔙 Cancel", callback_data="cancel")
        ]
    ])
    
    msg = (
        f"♻️ *Renew Your Subscription*\n\n"
        f"Your current tier: *{current_tier.capitalize()}*\n"
        f"Expiry date: *{expiry_str}*\n\n"
        f"Choose a renewal period:\n"
    )
    
    if query:
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=duration_keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=duration_keyboard)
    
    return SELECTING_DURATION


async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show payment details with live SOL conversion."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Retrieve selected duration
    duration_months = query.data.split("_")[1]
    context.user_data['duration'] = duration_months
    current_tier = context.user_data.get('current_tier')

    if not current_tier or not duration_months:
        await query.message.edit_text("⚠️ Missing renewal details. Please restart with /renew.")
        return ConversationHandler.END

    chosen_wallet = wallets.get_random_wallet()
    if not chosen_wallet:
        await query.message.edit_text("❌ No wallets available for payment at this time. Please try again later.")
        return ConversationHandler.END

    # Mark wallet as in-use
    wallets.set_wallet_status(chosen_wallet, "in-use")

    # Set price in USD based on tier and duration
    tier_prices_usd = {
        "disciple": {"1": 5, "6": 8, "12": 10},
        "chieftain": {"1": 5, "6": 8, "12": 20},
        "overlord": {"1": 5, "6": 8, "12": 10}
    }

    price_usd = tier_prices_usd[current_tier][duration_months]

    # Fetch live SOL price for USD equivalent (for reference)
    sol_price_usd = await fetch_sol_price_usd()
    # Convert USD price to SOL equivalent
    price_sol = round(price_usd / sol_price_usd, 2)

    # Generate random payment ID
    payment_id = secrets.token_urlsafe(8)

    # Save details to context for later verification
    context.user_data.update({
        "payment_wallet": chosen_wallet,
        "payment_amount_sol": price_sol,
        "payment_amount_usd": price_usd,
        "payment_reference": payment_id,
        "payment_start_time": datetime.now()
    })

    # Generate QR code (wallet address only)
    qr = qrcode.make(chosen_wallet)
    bio = io.BytesIO()
    bio.name = 'qr.png'
    qr.save(bio, 'PNG')
    bio.seek(0)

    # Build payment message
    payment_para_1 = (
        "For a quicker and easier payment verification, kindly send payments "
        "from a non-custodial wallet like Phantom, Solflare etc "
        "instead of a centralized exchange, as exchange transactions "
        "can take longer and may cause issues."
    )

    payment_msg = (
        f"♻️ *Renewal Payment Details*\n\n"
        f"You are renewing your *{current_tier.capitalize()}* tier for {duration_months} months.\n\n"
        f"{payment_para_1}\n\n"
        f"Send `{price_sol} SOL` (≈ ${price_usd}) to the *wallet address:* `{chosen_wallet}`\n\n"
        f"⏳ Please complete the payment within *10 minutes* to avoid expiration.\n\n"
        f"Once done, click *'I've Paid'* below and you will be asked for the transaction hash / signature for verification\n\n"
        f"{DIVIDER_LINE}\n"
        f"Incase of verification failure provide the data below to the admin for manual verification\n\n"
        f"👤 Your User ID: `{user_id}`\n"
        f"🆔 Your Payment ID: `{payment_id}`"
    )

    payment_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I've Paid", callback_data="verify")],
        [
         InlineKeyboardButton("🔙 Back", callback_data="back"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ]
    ])

    # Send payment instructions + QR code
    await query.message.delete()
    await update.effective_chat.send_photo(
        photo=InputFile(bio),
        caption=payment_msg,
        parse_mode="Markdown",
        reply_markup=payment_keyboard
    )

    return PAYMENT


# === VERIFY FROM HASH ===
async def verify_payment_from_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user_id = update.effective_user.id

    wallet_address = context.user_data.get("payment_wallet")
    amount_expected = context.user_data.get("payment_amount_sol")
    start_time = context.user_data.get("payment_start_time")
    current_tier = context.user_data.get("current_tier")
    duration_months = context.user_data.get("duration")
    payment_reference = context.user_data.get("payment_reference")
    renewal_fee_usd = context.user_data.get("payment_amount_usd", 0)

    if not (wallet_address and amount_expected and start_time and current_tier and duration_months):
        await update.message.reply_text("⚠️ Payment session expired or invalid. Please restart with /renew.")
        return ConversationHandler.END

    now = datetime.now()
    if now > start_time + timedelta(minutes=10):
        await update.message.reply_text("⌛ Payment window expired. Please start again with /renew.")
        return ConversationHandler.END

    tx_sig = user_input.strip()
    
    # ✅ Log new payment only after hash is submitted
    payment_logs.log_user_payment(user_id, payment_reference, {
        "action": "renewal",
        "tier": current_tier,
        "duration_months": duration_months,
        "payment_wallet": wallet_address,
        "amount_in_sol": amount_expected,
        "amount_in_usd": renewal_fee_usd,
        "start_time": start_time.isoformat(),
        "tx_sig": tx_sig
    })

    # === Call Solana RPC to get transaction info ===
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [tx_sig, {"encoding": "jsonParsed"}]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(SOLANA_RPC, headers=headers, json=payload) as resp:
            data = await resp.json()

    transaction = data.get("result")
    if not transaction:
        await update.message.reply_text("❌ Could not find transaction on-chain. Check your hash and try again.")
        return ASK_TRANSACTION_HASH

    block_time = transaction.get("blockTime")
    if block_time:
        tx_time = datetime.fromtimestamp(block_time)
        if tx_time < start_time or tx_time > start_time + timedelta(minutes=10):
            await update.message.reply_text("⏱️ Transaction timestamp is outside the valid payment window.")
            return ASK_TRANSACTION_HASH

    message = transaction["transaction"]["message"]
    account_keys = message.get("accountKeys", [])
    sender_pubkey = next((acc.get("pubkey") for acc in account_keys if isinstance(acc, dict) and acc.get("signer")), None)

    # === Check SOL transfer ===
    instructions = message["instructions"]
    for instr in instructions:
        parsed = instr.get("parsed", {})
        if parsed.get("type") == "transfer":
            info = parsed.get("info", {})
            dest = info.get("destination")
            lamports = int(info.get("lamports", 0))
            sol_amount = lamports / 10**SOL_DECIMALS

            if dest == wallet_address and abs(sol_amount - amount_expected) <= SOL_PAYMENT_TOLERANCE:
                # === Payment verified — handle renewal ===
                # Get current expiry and extend it
                current_expiry = tiers.get_user_expiry(user_id)
                
                # Parse expiry if it's a string
                if isinstance(current_expiry, str):
                    try:
                        current_expiry = datetime.fromisoformat(current_expiry)
                    except ValueError:
                        # If we can't parse it, start from now
                        current_expiry = datetime.now()
                
                # If expiry is in the past, start from now
                if not current_expiry or current_expiry < datetime.now():
                    new_expiry = datetime.now() + timedelta(days=int(duration_months) * 30)
                else:
                    # Otherwise extend from current expiry
                    new_expiry = current_expiry + timedelta(days=int(duration_months) * 30)
                
                # Update expiry
                tiers.set_user_expiry(user_id, new_expiry)

                # Mark wallet as available
                wallets.mark_wallet_as_available(wallet_address)

                # Process referral commission if applicable (for 6+ month renewals)
                if int(duration_months) >= 6:
                    referral_success, commission, referrer_id = on_upgrade_completed(user_id, renewal_fee_usd, int(duration_months))
                    
                    if referral_success and referrer_id:
                        # Get referrer and referred user info
                        try:
                            referrer = await context.bot.get_chat(referrer_id)
                            referred = await context.bot.get_chat(user_id)
                            
                            referrer_name = referrer.full_name or f"User {referrer_id}"
                            referred_name = referred.full_name or f"User {user_id}"
                            
                            # Notify referrer about their commission
                            await send_message(
                                context.bot,
                                f"🎉 Hey {referrer_name},\n\nYou just earned ${commission:.2f} commission from {referred_name}'s renewal!",
                                chat_id=referrer_id
                            )
                            
                            # Log referral commission for admin
                            await send_message(
                                context.bot,
                                f"📣 Referral bonus:\n\nReferrer {referrer_name} (ID: `{referrer_id}`) earned ${commission:.2f} commission from {referred_name} (ID: `{user_id}`) after renewing {current_tier.capitalize()} for {duration_months} month(s).",
                                chat_id=BOT_REFERRAL_LOGS_ID,
                                super_admin=SUPER_ADMIN_ID
                            )
                        except Exception as e:
                            # If we have an error, log with available information
                            await send_message(
                                context.bot,
                                f"💰 Referral commission of ${commission:.2f} awarded to User ID: `{referrer_id}` "
                                f"for User ID: `{user_id}`'s {duration_months}-month renewal. Error getting details: {e}",
                                chat_id=BOT_REFERRAL_LOGS_ID
                            )
                    else:

                        # Handle if user was not referred by another user
                        referred = await context.bot.get_chat(user_id)
                        referred_name = referred.full_name or f"User {user_id}"

                await send_message(
                            context.bot,
                            f"♻️ User {referred_name} (ID: `{user_id}`) has successfully renewed their *{current_tier.capitalize()}* tier for {duration_months} month(s).\n\n"
                            f"⏳ New Expiry: {new_expiry.strftime('%d %b %Y')} | Ref: `{payment_reference}`",
                            chat_id=BOT_INFO_LOGS_ID
                        )

                complete_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Back to Dashboard", callback_data="complete")]
                ])

                success_msg = (
                    f"✅ *Renewal Successful!*\n\n"
                    f"Your {current_tier.capitalize()} tier has been renewed for {duration_months} month(s).\n"
                    f"Your subscription will now expire on: {new_expiry.strftime('%d %b %Y')}.\n\n"
                    f"Thank you for continuing with us!"
                )

                await update.message.reply_text(success_msg, parse_mode="Markdown", reply_markup=complete_keyboard)

                # Auto-forward funds
                success_forward, result = await forward_user_payment(wallet_address, context)
                
                if not success_forward:
                    await send_message(
                        context.bot,
                        f"⚠️ Auto-forward failed for {user_id} ({wallet_address}) — Error: {result}",
                        chat_id=BOT_ERROR_LOGS_ID
                    )
                return VERIFICATION

    # Payment verification failed
    fail_msg = (
        "❌ *Payment Not Verified*\n\n"
        "No matching SOL transfer was found in the provided transaction.\n"
        "Please make sure:\n"
        f"- You sent the correct amount: `{amount_expected}` SOL\n"
        f"- To the correct address: `{wallet_address}`\n"
        "- Within the 10-minute window\n\n"
        f"🆔 *Your Payment Reference:* `{payment_reference}`\n"
        f"👤 *Your User ID:* `{user_id}`\n\n"
        f"If you believe this is an error, [contact support]({BOT_TG_GROUP}) with your payment reference and user ID"
    )

    await update.message.reply_text(fail_msg, parse_mode="Markdown", disable_web_page_preview=True)
    return ConversationHandler.END


async def back_to_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Revert the wallet status
    wallets.revert_wallet_status_from_context(context)
    
    # Delete current message with QR code
    try:
        await query.message.delete()
    except Exception:
        # If we can't delete it, continue anyway
        pass
    
    current_tier = context.user_data.get('current_tier')
    expiry_date = tiers.get_user_expiry(user_id=int(query.message.chat_id))
    
    # Format expiry date
    expiry_str = "Not set"
    if expiry_date:
        if isinstance(expiry_date, str):
            try:
                expiry_date = datetime.fromisoformat(expiry_date)
                expiry_str = expiry_date.strftime("%d %b %Y")
            except ValueError:
                expiry_str = expiry_date
        else:
            expiry_str = expiry_date.strftime("%d %b %Y")
    
    # Create duration options
    duration_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗓️ 1 Month", callback_data="duration_1"),
            InlineKeyboardButton("⭐ 6 Months", callback_data="duration_6")
        ],
        [
            InlineKeyboardButton("🔥 1 Year", callback_data="duration_12")
        ],
        [
            InlineKeyboardButton("🔙 Cancel", callback_data="cancel")
        ]
    ])
    
    msg = (
        f"♻️ *Renew Your Subscription*\n\n"
        f"Your current tier: *{current_tier.capitalize()}*\n"
        f"Expiry date: *{expiry_str}*\n\n"
        f"Choose a renewal period:\n"
    )
    
    await update.effective_chat.send_message(
        text=msg, 
        parse_mode="Markdown", 
        reply_markup=duration_keyboard
    )
    
    return SELECTING_DURATION


async def complete_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End the conversation and go back to dashboard."""
    if update.callback_query:
        await update.callback_query.answer()

    try:
        await go_back_to_dashboard(update, context)
    except Exception as e:
        await update.effective_chat.send_message("⚠️ Failed to return to dashboard.")
        raise e

    context.user_data.clear()
    return ConversationHandler.END


async def retry_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retry payment verification safely."""
    query = update.callback_query
    await query.answer()

    # Check required payment reference
    if not context.user_data.get("payment_reference"):
        await query.message.edit_text(
            "⚠️ Missing payment information. Please restart the renewal process with /renew.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Safe to retry
    return await verify_payment_from_hash(update, context)


async def cancel_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the renewal process and return to dashboard."""
    # Revert the status of the assigned wallet from in-use to available
    wallets.revert_wallet_status_from_context(context)

    if update.callback_query:
        await update.callback_query.answer()
        context.user_data.clear()
        try:
            
            await go_back_to_dashboard(update, context)
            await asyncio.sleep(2)
            await update.callback_query.message.delete()
        except Exception as e:
            await update.effective_chat.send_message("⚠️ Failed to return to dashboard.")
            raise e
    else:
        await update.message.reply_text("Renewal canceled. Use /lc to return to main menu.")
        context.user_data.clear()

    return ConversationHandler.END


# === RENEWAL CONVERSATION HANDLER ===
renewal_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("renew", start_renewal),
        CallbackQueryHandler(start_renewal, pattern="^cmd_renew$")
    ],
    states={
        SELECTING_DURATION: [
            CallbackQueryHandler(handle_payment, pattern="^duration_"),
            CallbackQueryHandler(cancel_renewal, pattern="^cancel$")
        ],
        PAYMENT: [
            CallbackQueryHandler(prompt_transaction_hash, pattern="^verify$"),
            CallbackQueryHandler(back_to_duration, pattern="^back$"),
            CallbackQueryHandler(cancel_renewal, pattern="^cancel$")
        ],
        ASK_TRANSACTION_HASH: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, verify_payment_from_hash)
        ],
        VERIFICATION: [
            CallbackQueryHandler(complete_renewal, pattern="^complete$"),
            CallbackQueryHandler(retry_verification, pattern="^retry$")
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_renewal),
        CallbackQueryHandler(cancel_renewal, pattern="^cancel$")
    ],
    name="renewal_conversation",
    persistent=False
)