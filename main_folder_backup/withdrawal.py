# withdrawal.py
import logging
import html
import time
from typing import Tuple, Union
from base58 import b58decode

from solana.rpc.api import Client
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.transaction import Transaction # type: ignore
from solders.message import Message # type: ignore
from solders.system_program import transfer, TransferParams
from solders.signature import Signature # type: ignore

from telegram.ext import ContextTypes
from secrets_key import get_decrypted_wallet
from storage.payout import get_next_payout_wallet

from util.utils import send_message
from config import (SOLANA_RPC, DEFAULT_FEE_LAMPORTS, LAMPORTS_PER_SOL,
                    BOT_PAYMENT_LOGS_ID
                    )

logger = logging.getLogger(__name__)

# Initialize Solana client
SOLANA_CLIENT = Client(SOLANA_RPC)
# Determine if we're on mainnet or devnet
IS_MAINNET = "mainnet" in SOLANA_RPC.lower()
CLUSTER = "mainnet" if IS_MAINNET else "devnet"

# Constants
MAX_CONFIRMATION_ATTEMPTS = 20
CONFIRMATION_CHECK_INTERVAL = 3  # seconds
MIN_BALANCE_FOR_RENT = 890880  # Minimum balance to keep account rent exempt (~0.00089 SOL)


async def forward_user_payment(from_address: str, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    """
    Forwards funds from user's payment wallet to a payout wallet.

    Returns:
        (True, tx_signature) on success,
        (False, error_message) on failure
    """
    try:
        # Get private key for the wallet
        private_key_b58 = get_decrypted_wallet(from_address)
        if not private_key_b58:
            logger.error(f"Private key not found for wallet: {from_address}")
            return False, "Private key not found for wallet."

        keypair = Keypair.from_bytes(b58decode(private_key_b58))

        # Get destination payout wallet
        to_address = get_next_payout_wallet()
        if not to_address:
            logger.error("No payout wallet available.")
            return False, "No payout wallet available."

        to_pubkey = Pubkey.from_string(to_address)

        # Check balance with consideration for rent-exempt minimum
        balance_response = SOLANA_CLIENT.get_balance(keypair.pubkey())
        if not balance_response.value:
            logger.error(f"Failed to get balance for wallet: {from_address}")
            return False, "Failed to get wallet balance."
            
        balance = balance_response.value
        fee_buffer = DEFAULT_FEE_LAMPORTS * 2
        
        # Make sure we leave enough for rent exemption plus fees
        min_required = MIN_BALANCE_FOR_RENT + fee_buffer
        
        if balance <= min_required:
            logger.warning(f"Insufficient balance: {balance} lamports (need at least {min_required}) for wallet: {from_address}")
            return False, f"Insufficient balance: {balance} lamports (need at least {min_required})"

        # Calculate amount to transfer (leaving enough for rent + fees)
        amount = balance - min_required
        sol_amount = round(amount / LAMPORTS_PER_SOL, 4)
        
        logger.info(f"Forwarding {sol_amount} SOL from {from_address} to {to_address}")

        # Create instruction
        instruction = transfer(TransferParams(
            from_pubkey=keypair.pubkey(),
            to_pubkey=to_pubkey,
            lamports=amount
        ))

        # Build transaction
        blockhash_response = SOLANA_CLIENT.get_latest_blockhash()
        if not blockhash_response.value:
            logger.error("Failed to get latest blockhash")
            return False, "Failed to get latest blockhash"
            
        recent_blockhash = blockhash_response.value.blockhash
        message = Message.new_with_blockhash(
            [instruction],
            keypair.pubkey(),
            recent_blockhash
        )
        txn = Transaction([keypair], message, recent_blockhash)

        # Send transaction
        try:
            send_response = SOLANA_CLIENT.send_transaction(txn)
            if not send_response.value:
                logger.error("Failed to send transaction")
                return False, "Failed to send transaction"
                
            sig = send_response.value
            logger.info(f"Sent transaction {sig}")
        except Exception as e:
            logger.error(f"Error sending transaction: {e}")
            return False, f"Error sending transaction: {str(e)}"

        # Confirm status - using the approach from test_withdrawal.py
        for attempt in range(MAX_CONFIRMATION_ATTEMPTS):
            try:
                status_resp = SOLANA_CLIENT.get_signature_statuses([sig])
                if not status_resp or not status_resp.value or not status_resp.value[0]:
                    logger.info(f"Transaction status not available yet, attempt {attempt + 1}/{MAX_CONFIRMATION_ATTEMPTS}")
                    time.sleep(CONFIRMATION_CHECK_INTERVAL)
                    continue
                    
                status = status_resp.value[0]
                if status:
                    # Check for errors
                    err = status.err
                    if err:
                        logger.error(f"Transaction failed: {err}")
                        return False, f"Transaction failed: {err}"
                    
                    # Get confirmation status
                    conf_status = status.confirmation_status
                    logger.info(f"Transaction status: {conf_status}, attempt {attempt + 1}/{MAX_CONFIRMATION_ATTEMPTS}")
                    
                    # Let's print the raw type and value to debug
                    logger.info(f"Status type: {type(conf_status)}, repr: {repr(conf_status)}")
                    
                    # Try multiple methods to detect Finalized status
                    is_finalized = False
                    
                    # Method 1: Direct string check in the string representation
                    if "Finalized" in str(conf_status):
                        is_finalized = True
                    # Method 2: Try using the enum value if it has a value attribute
                    elif hasattr(conf_status, 'value') and conf_status.value == 'finalized':
                        is_finalized = True
                    # Method 3: As a last resort, check if the status itself is "finalized"
                    elif conf_status == "finalized":
                        is_finalized = True
                        
                    if is_finalized:
                        # # Transaction is confirmed, mark wallet as available
                        # wallets.mark_wallet_as_available(from_address)
                        
                        # Success! Now let's notify, but with better error handling
                        return await _notify_successful_transfer(
                            context, from_address, to_address, sol_amount, sig
                        )
            except Exception as e:
                logger.error(f"Error checking transaction status: {e}")
                # Continue trying despite error
            
            time.sleep(CONFIRMATION_CHECK_INTERVAL)

        # If we get here, transaction timed out
        logger.error(f"Transaction {sig} not finalized after {MAX_CONFIRMATION_ATTEMPTS} attempts")
        return False, f"Transaction {sig} not finalized after waiting."

    except Exception as e:
        logger.exception(f"Unexpected error in forward_user_payment: {e}")
        return False, str(e)


async def _notify_successful_transfer(
    context: ContextTypes.DEFAULT_TYPE, 
    from_address: str, 
    to_address: str, 
    sol_amount: float, 
    sig: Union[str, Signature]
) -> Tuple[bool, str]:
    """
    Notify about successful transaction and handle any notification errors.
    """
    try:
        # Format the upgrade fee display
        upgrade_fee = context.user_data.get("payment_amount_usdc")
        usd_display = f" (~${upgrade_fee:.2f})" if upgrade_fee is not None and isinstance(upgrade_fee, (int, float)) else ""

        # Build message with proper escaping for HTML
        from_addr_escaped = html.escape(from_address)
        to_addr_escaped = html.escape(to_address)

        sig_str = html.escape(str(sig))

        #sig_escaped = html.escape(sig)
        usd_escaped = html.escape(usd_display)
        
        # Create message with correct explorer link for the current cluster
        msg = (
            f"💸 <b>Payment Forwarded Successfully!</b>\n\n"
            f"🔁 From: <code>{from_addr_escaped}</code>\n"
            f"📥 To: <code>{to_addr_escaped}</code>\n"
            f"💰 Amount: {sol_amount} SOL{usd_escaped}\n"
            f"🔗 <a href='https://explorer.solana.com/tx/{sig_str}?cluster={CLUSTER}'>View TX</a>"
        )

        # Send notification with error handling and fallback
        try:
            await send_message(
                context.bot,
                msg,
                chat_id=BOT_PAYMENT_LOGS_ID,
                parse_mode="HTML",
                #disable_web_page_preview=True
            )
            logger.info("Payment notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send HTML notification: {e}")
            
            # Fallback to plain text if HTML parsing fails
            try:
                # Simplified plain text message without HTML tags
                plain_msg = (
                    f"Payment Forwarded Successfully!\n\n"
                    f"From: {from_address}\n"
                    f"To: {to_address}\n"
                    f"Amount: {sol_amount} SOL{usd_display}\n"
                    f"View TX: https://explorer.solana.com/tx/{sig}?cluster={CLUSTER}"
                )
                
                await send_message(
                    context.bot,
                    plain_msg,
                    chat_id=BOT_PAYMENT_LOGS_ID,
                    parse_mode=None,  # No parsing
                    #disable_web_page_preview=True
                )
                logger.info("Plain text notification sent as fallback")
            except Exception as e2:
                logger.error(f"Failed to send plain text notification: {e2}")
                # Continue with success flow even if both notification attempts fail
        
        # Return success regardless of notification status
        return True, sig
        
    except Exception as e:
        logger.error(f"Error in notification formatting: {e}")
        # Even if notification fails, the transaction was successful
        return True, sig