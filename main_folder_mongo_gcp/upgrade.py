import asyncio
import aiohttp
import qrcode
import io
import secrets


from telegram.error import BadRequest
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters
                          )


import storage.tiers as tiers

from storage import wallets
from storage import payment_logs
from withdrawal import forward_user_payment, run_forward_user_payment

from datetime import datetime, timedelta

from util.utils import build_custom_update_from_query, send_message
from config import (SUPER_ADMIN_ID, BOT_ERROR_LOGS_ID, DIVIDER_LINE, BOT_TG_GROUP,
                    SOLANA_RPC, SOL_DECIMALS, SOL_PAYMENT_TOLERANCE,
                    BOT_INFO_LOGS_ID, BOT_REFERRAL_LOGS_ID
                    )

from referral import on_upgrade_completed


# === STATE CONSTANTS ===
SELECTING_TIER, SELECTING_DURATION, PAYMENT, ASK_TRANSACTION_HASH, VERIFICATION = range(5)


async def fetch_sol_price_usd() -> float:
    """Fetch current SOL price in USD from CoinGecko."""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            return data['solana']['usd']

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

async def go_back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    launch_func = context.bot_data.get("launch_dashboard")
    # if launch_func:
    #     custom_update = build_custom_update_from_query(update.callback_query)
    #     return await launch_func(custom_update, context)
    
    if launch_func:
        try:
            custom_update = build_custom_update_from_query(update.callback_query)
        except AttributeError:
            custom_update = update  # fallback to raw update for command-based entry

        return await launch_func(custom_update, context)

    else:
        try:
            await update.callback_query.edit_message_text("⚠️ Dashboard unavailable.")
        except BadRequest as e:
            if "message to edit" in str(e):
                await update.effective_chat.send_message("⚠️ Dashboard unavailable.")
            else:
                raise

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

    if current_tier == "super admin":
        # Send a message directing them to use the /upgrade command instead
        super_msg = "This command is not designed for you, O the *CEO*"
           
        await message.reply_text(
            super_msg,
            parse_mode="Markdown",
        )
        return

    # Store the original message if we need to return to dashboard
    if hasattr(update, 'callback_query') and update.callback_query:
        context.user_data['dashboard_message'] = update.callback_query.message
    
    else:
        # User came from /upgrade command — simulate dashboard context
        context.user_data['from_dashboard'] = True
        context.user_data['dashboard_message'] = message  # fallback to current command msg

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
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="cancel")])
        
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
        # "disciple": {"1": 10, "6": 54, "12": 102},
        # "chieftain": {"1": 20, "6": 108, "12": 204},
        # "overlord": {"1": 40, "6": 216, "12": 408}
        "disciple": {"1": 5, "6": 8, "12": 10},
        "chieftain": {"1": 5, "6": 8, "12": 10},
        "overlord": {"1": 5, "6": 8, "12": 10}
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
    f"🗓️ 1 Month: <b>{one_month_price} USD</b>\n\n"
    f"⭐ 6 Months:\n"
    f"<s>{six_months_original} USD</s> ➔ <b>{six_months_price} USD</b>  🏷️ <b>Save {six_months_saved} USD (10%)</b>\n\n"
    f"🔥 1 Year:\n"
    f"<s>{twelve_months_original} USD</s> ➔ <b>{twelve_months_price} USD</b>  🏷️ <b>Save {twelve_months_saved} USD (15%)</b>\n"
    )

    await query.message.edit_text(msg, parse_mode="HTML", reply_markup=duration_keyboard)
    return SELECTING_DURATION

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show payment details with live SOL conversion."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Retrieve selected tier and duration
    duration_months = query.data.split("_")[1]
    context.user_data['duration'] = duration_months
    selected_tier = context.user_data.get('selected_tier')

    if not selected_tier or not duration_months:
        await query.message.edit_text("⚠️ Missing upgrade details. Please restart with /upgrade.")
        return ConversationHandler.END


    chosen_wallet = await wallets.get_random_wallet()
    if not chosen_wallet:
        await query.message.edit_text("❌ No wallets available for payment at this time. Please try again later.")
        return ConversationHandler.END

    # Mark wallet as in-use
    await wallets.set_wallet_status(chosen_wallet, "in-use")


    # Set price in USDC based on duration (you can customize this mapping)
    tier_prices_usdc = {
        # "disciple": {"1": 10, "6": 54, "12": 102},
        # "chieftain": {"1": 20, "6": 108, "12": 204},
        # "overlord": {"1": 40, "6": 216, "12": 408}
        "disciple": {"1": 5, "6": 8, "12": 10},
        "chieftain": {"1": 5, "6": 20, "12": 10},
        "overlord": {"1": 5, "6": 8, "12": 10}
    }

    price_usdc = tier_prices_usdc[selected_tier][duration_months]

    # Fetch live SOL price
    sol_price_usd = await fetch_sol_price_usd()

    # Calculate SOL equivalent
    amount_in_sol = round(price_usdc / sol_price_usd, 2)

    # Generate random payment ID
    payment_id = secrets.token_urlsafe(8)

    # Save details to context for later verification
    context.user_data.update({
        "payment_wallet": chosen_wallet,
        "payment_amount_usdc": price_usdc,
        "payment_amount_sol": amount_in_sol,
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
        f"💎 *Upgrade Payment Details*\n\n"
        f"You have selected *{selected_tier.capitalize()}* tier for {duration_months} months.\n\n"
        f"{payment_para_1}\n\n"
        f"Send `{amount_in_sol} SOL` to the *wallet address:* `{chosen_wallet}`\n\n"
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
    context.user_data["from_payment"] = True


    return PAYMENT


# === VERIFY FROM HASH ===
async def verify_payment_from_hash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user_id = update.effective_user.id

    wallet_address = context.user_data.get("payment_wallet")
    amount_expected = context.user_data.get("payment_amount_sol")
    start_time = context.user_data.get("payment_start_time")
    selected_tier = context.user_data.get("selected_tier")
    duration_months = context.user_data.get("duration")
    payment_reference = context.user_data.get("payment_reference")
    upgrade_fee = context.user_data.get("payment_amount_usdc", 0)

    if not (wallet_address and amount_expected and start_time and selected_tier and duration_months):
        await update.message.reply_text("⚠️ Payment session expired or invalid. Please restart with /upgrade.")
        return ConversationHandler.END

    now = datetime.now()
    if now > start_time + timedelta(minutes=10):
        await update.message.reply_text("⌛ Payment window expired. Please start again with /upgrade.")
        return ConversationHandler.END

    tx_sig = user_input.strip()
    
    # ✅ Log new payment only after hash is submitted
    await payment_logs.log_user_payment(user_id, payment_reference, {
    "tier": selected_tier,
    "duration_months": duration_months,
    "payment_wallet": wallet_address,
    "amount_in_usdc": upgrade_fee,
    "amount_in_sol": amount_expected,
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
                # === Payment verified — handle upgrade ===
                await tiers.set_user_tier(user_id, selected_tier)
                expiry_date = datetime.now() + timedelta(days=int(duration_months) * 30)
                await tiers.set_user_expiry(user_id, expiry_date)

                await wallets.mark_wallet_as_available(wallet_address)

                success, commission, referrer_id = await on_upgrade_completed(user_id, upgrade_fee, int(duration_months))

                # Process referral commission if applicable (for 6+ month upgrade)
                if success and referrer_id:
                    # Get referrer and referred user info
                    referrer = await context.bot.get_chat(referrer_id)
                    referred = await context.bot.get_chat(user_id)

                    referrer_name = referrer.full_name or f"User {referrer_id}"
                    referred_name = referred.full_name or f"User {user_id}"

                    # Notify referrer about their commission
                    await send_message(
                        context.bot,
                        f"🎉 Hey {referrer_name},\n\nYou just earned ${commission:.2f} commission from referring {referred_name}!",
                        chat_id=referrer_id
                    )

                    # Log referral commission for admin
                    await send_message(
                        context.bot,
                        f"📣 Referral bonus:\n\nReferrer {referrer_name} (ID: `{referrer_id}`) earned ${commission:.2f} commission from referring {referred_name} (ID: `{user_id}`) after upgrading to {selected_tier.capitalize()} for {duration_months} month(s).",
                        chat_id=BOT_REFERRAL_LOGS_ID,
                        super_admin=SUPER_ADMIN_ID
                    )
                else:
                    # Handle if user was not referred by another user
                    referred = await context.bot.get_chat(user_id)
                    referred_name = referred.full_name or f"User {user_id}"

                await send_message(
                    context.bot,
                    f"📢 User {referred_name} (ID: `{user_id}`) has successfully upgraded to *{selected_tier.capitalize()}* tier for {duration_months} month(s).\n\n"
                    f"⏳ Expiry: {expiry_date.strftime('%d %b %Y')} | Ref: `{payment_reference}`",
                    chat_id=BOT_INFO_LOGS_ID
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

                await update.message.reply_text(success_msg, parse_mode="Markdown", reply_markup=complete_keyboard)

                # # Auto-forward funds
                # success_forward, result = await forward_user_payment(wallet_address, context)

                # if not success_forward:
                #     #await update.message.reply_text(f"⚠️ Upgrade successful, but auto-forward failed:\n{result}")
                #     await send_message(
                #         context.bot,
                #         f"⚠️ Auto-forward failed for {user_id} ({wallet_address}) — Error: {result}",
                #         chat_id=BOT_ERROR_LOGS_ID
                #     )

                # Start background auto-forward
                asyncio.create_task(run_forward_user_payment(wallet_address, context, user_id))
                return VERIFICATION

    
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
    

async def complete_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "⚠️ Missing payment information. Please restart the upgrade process with /upgrade.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Safe to retry
    return await verify_payment_from_hash(update, context)


async def back_to_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to tier selection."""
    query = update.callback_query
    await query.answer()
    return await start_upgrade(update, context)


async def back_to_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Used to revert the status of the assigned wallet from
    # in-use to available
    await wallets.revert_wallet_status_from_context(context)

    if "selected_tier" not in context.user_data or "duration" not in context.user_data:
        await update.callback_query.message.edit_text("⚠️ Session expired. Please restart with /upgrade.")
        return ConversationHandler.END

    selected_tier = context.user_data['selected_tier']
    
    # First delete the current message with QR code
    try:
        await query.message.delete()
    except Exception:
        # If we can't delete it, we'll try to continue anyway
        pass
    
    # Create tier options based on prices
    prices = {
        # "disciple": {"1": 10, "6": 54, "12": 102},
        # "chieftain": {"1": 20, "6": 108, "12": 204},
        # "overlord": {"1": 40, "6": 216, "12": 408}
        "disciple": {"1": 5, "6": 8, "12": 10},
        "chieftain": {"1": 5, "6": 8, "12": 10},
        "overlord": {"1": 5, "6": 8, "12": 10}
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
    f"🗓️ 1 Month: <b>{one_month_price} USD</b>\n\n"
    f"⭐ 6 Months:\n"
    f"<s>{six_months_original} USD</s> ➔ <b>{six_months_price} USD</b>  🏷️ <b>Save {six_months_saved} USD (10%)</b>\n\n"
    f"🔥 1 Year:\n"
    f"<s>{twelve_months_original} USD</s> ➔ <b>{twelve_months_price} USD</b>  🏷️ <b>Save {twelve_months_saved} USD (15%)</b>\n"
    )
    
    # Send a new message instead of editing
    await update.effective_chat.send_message(
        text=msg, 
        parse_mode="HTML", 
        reply_markup=duration_keyboard
    )
    context.user_data["from_payment"] = False

    return SELECTING_DURATION



async def cancel_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the upgrade process and return to dashboard."""
    await wallets.revert_wallet_status_from_context(context)

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await go_back_to_dashboard(update, context)

            if context.user_data.get("from_payment"):
                await asyncio.sleep(2)
                await update.callback_query.message.delete()
                
        except Exception as e:
            await update.effective_chat.send_message("⚠️ Failed to return to dashboard.")
            raise e
        finally:
            context.user_data.clear()
    else:
        await update.message.reply_text("Upgrade canceled. Use /lc to return to main menu.")
        context.user_data.clear()

    return ConversationHandler.END



# === UPGRADE CONVERSATION HANDLER ===
upgrade_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler(["upgrade", "u"], start_upgrade),
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
            CallbackQueryHandler(prompt_transaction_hash, pattern="^verify$"),
            CallbackQueryHandler(back_to_duration, pattern="^back$")
        ],
        ASK_TRANSACTION_HASH: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, verify_payment_from_hash)
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