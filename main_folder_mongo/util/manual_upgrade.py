# wallet_sync.py (inside utils/)

from datetime import datetime, timedelta
from config import SUPER_ADMIN_ID, BOT_ERROR_LOGS_ID, BOT_INFO_LOGS_ID
from referral import on_upgrade_completed
from storage.tiers import set_user_tier, set_user_expiry
from withdrawal import forward_user_payment
from util.utils import send_message
import storage.wallets as wallets
from telegram.ext import ContextTypes

import storage.expiry as expiry
import storage.tiers as tiers

async def complete_verified_upgrade(user_id: int, payment: dict, context: ContextTypes.DEFAULT_TYPE):
    tier = payment.get("tier")
    duration = int(payment.get("duration_months", 1))
    wallet_address = payment.get("payment_wallet")
    usdc_amount = float(payment.get("amount_in_usdc", 0))
    sol_amount = float(payment.get("amount_in_sol", 0))
    #reference = payment.get("payment_reference") or "-"
    reference = context.user_data.get("manual_payment_id") or "-" # Getting reference from the payment id input

    # Only update tier if different
    current_tier = tiers.USER_TIERS.get(user_id)
    if current_tier != tier:
        await set_user_tier(user_id, tier)

    new_expiry = datetime.now() + timedelta(days=duration * 30)
    current_expiry = expiry.USER_EXPIRY.get(user_id)

    if not current_expiry or new_expiry > current_expiry:
        set_user_expiry(user_id, new_expiry)


    # set assigned wallet back to available
    wallets.mark_wallet_as_available(wallet_address)

    # Referral + commission
    success, commission, referrer_id = on_upgrade_completed(user_id, usdc_amount, duration)

    # Process commission for the referrer
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
            f"📣 Referral bonus:\n\nReferrer {referrer_name} (ID: `{referrer_id}`) earned ${commission:.2f} commission from referring {referred_name} (ID: `{user_id}`) after upgrading to {tier.capitalize()} for {duration} month(s).",
            chat_id=BOT_INFO_LOGS_ID,
            super_admin=SUPER_ADMIN_ID
        )
    else:
        # Handle if user was not referred by another user
        referred = await context.bot.get_chat(user_id)
        referred_name = referred.full_name or f"User {user_id}"

    # Confirmation
    await send_message(
        context.bot,
        f"📢 User {referred_name} (ID: `{user_id}`) manually upgraded to *{tier.capitalize()}* tier for {duration} month(s).\n\n"
        f"⏳ Expiry: {new_expiry.strftime('%d %b %Y')} | Ref: `{reference}`",
        chat_id=BOT_INFO_LOGS_ID,
        parse_mode="Markdown"
    )

    # Auto-forward payment
    success_forward, result = await forward_user_payment(wallet_address, context)
    if not success_forward:
        await send_message(
            context.bot,
            f"⚠️ Auto-forward failed for {user_id} ({wallet_address}) — Error: {result}",
            chat_id=BOT_ERROR_LOGS_ID
        )
