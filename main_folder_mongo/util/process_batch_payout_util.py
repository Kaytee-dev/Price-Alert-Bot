# Required solders imports for SPL token operations
from solders.pubkey import Pubkey  # type: ignore
from solders.instruction import Instruction, AccountMeta  # type: ignore
from solders.transaction import Transaction  # type: ignore
from solders.message import Message  # type: ignore
from solders.keypair import Keypair  # type: ignore

import logging
from typing import Tuple, Union, List, Tuple, Dict, Any
from base58 import b58decode

from solana.rpc.api import Client
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.transaction import Transaction # type: ignore
from solders.message import Message # type: ignore
from solders.system_program import transfer, TransferParams
from solders.signature import Signature # type: ignore
from solana.rpc.api import Client

from telegram.ext import ContextTypes
import asyncio
import aiohttp
from upgrade import fetch_sol_price_usd

logger = logging.getLogger(__name__)

# Add constants from withdrawal.py
MAX_CONFIRMATION_ATTEMPTS = 20
CONFIRMATION_CHECK_INTERVAL = 3  # seconds


SOLANA_CLIENT = Client("https://api.devnet.solana.com")

# Constants for fee calculation
ATA_CREATION_FEE_SOL = 0.0022  # SOL cost to create an Associated Token Account

# Constants for batch processing
MAX_ACCOUNTS_PER_TX = 10  # Max number of token accounts per transaction (can adjust based on testing)
MAX_BATCH_SIZE = 5  # Maximum number of payments to include in a single transaction

async def process_batch_payouts(
    payment_batch: List[Tuple[str, str, float]],  # List of (user_id, wallet_address, amount_usdc)
    keypair: Keypair,
    context: ContextTypes.DEFAULT_TYPE
) -> List[Tuple[str, bool, str, str]]:  # Returns list of (user_id, success, tx_sig, message)
    """
    Process a batch of USDC payments in optimized transactions.
    
    Args:
        payment_batch: List of tuples containing (user_id, wallet_address, amount_usdc)
        keypair: The sender's keypair
        context: Telegram context
        
    Returns:
        List of tuples containing (user_id, success, tx_signature, message)
    """
    try:
        logger.info(f"Processing batch of {len(payment_batch)} USDC payments")
        
        # SPL Token Program ID
        TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
        SYSVAR_RENT_PUBKEY = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
        
        # USDC mint address (mainnet)
        #USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

        # USDC mint address (devnet)
        USDC_MINT = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
        
        sender_pubkey = keypair.pubkey()
        sender_token_account = find_associated_token_address(sender_pubkey, USDC_MINT)
        
        # Helper to divide payments into optimal batches
        def create_optimized_batches(payments):
            # First, check which receivers need ATAs created
            needs_ata_creation = []
            no_ata_creation = []
            
            for payment in payments:
                user_id, wallet_address, _ = payment
                receiver_pubkey = Pubkey.from_string(wallet_address)
                receiver_token_account = find_associated_token_address(receiver_pubkey, USDC_MINT)
                
                # Check if receiver's token account exists
                account_info_response = SOLANA_CLIENT.get_account_info(receiver_token_account)
                if account_info_response.value is None:
                    needs_ata_creation.append(payment)
                else:
                    no_ata_creation.append(payment)
            
            # # We'll process those needing ATAs individually since each needs 2 instructions
            # individual_batches = [[payment] for payment in needs_ata_creation]

            # Group payments needing ATA creation into batches of 2
            individual_batches = []
            current_ata_batch = []
            for payment in needs_ata_creation:
                current_ata_batch.append(payment)
                if len(current_ata_batch) == 2:
                    individual_batches.append(current_ata_batch)
                    current_ata_batch = []
            if current_ata_batch:
                individual_batches.append(current_ata_batch)
            
            # For those not needing ATAs, we can batch more efficiently
            remaining_batches = []
            current_batch = []
            
            for payment in no_ata_creation:
                if len(current_batch) >= MAX_BATCH_SIZE:
                    remaining_batches.append(current_batch)
                    current_batch = []
                current_batch.append(payment)
                
            if current_batch:
                remaining_batches.append(current_batch)
                
            # Combine all batches
            return individual_batches + remaining_batches
        
        # Process all payment batches
        results = []
        optimized_batches = create_optimized_batches(payment_batch)
        
        logger.info(f"Split into {len(optimized_batches)} optimized transaction batches")
        
        for batch_idx, current_batch in enumerate(optimized_batches):
            logger.info(f"Processing batch {batch_idx+1}/{len(optimized_batches)} with {len(current_batch)} payments")
            
            # Get latest blockhash
            blockhash_response = SOLANA_CLIENT.get_latest_blockhash()
            if not blockhash_response.value:
                error_msg = "Failed to get latest blockhash"
                for user_id, wallet_address, _ in current_batch:
                    results.append((user_id, False, "", error_msg))
                continue
                
            recent_blockhash = blockhash_response.value.blockhash
            
            # Prepare instructions for this batch
            instructions = []
            
            # Track which users are in this transaction
            batch_user_info = []
            
            for user_id, wallet_address, amount_usdc in current_batch:
                receiver_pubkey = Pubkey.from_string(wallet_address)
                receiver_token_account = find_associated_token_address(receiver_pubkey, USDC_MINT)
                
                # Check if receiver's token account exists
                account_info_response = SOLANA_CLIENT.get_account_info(receiver_token_account)
                receiver_account_exists = account_info_response.value is not None
                
                # Store original amount for reference
                original_amount_usdc = amount_usdc
                adjusted_amount_usdc = amount_usdc
                ata_fee_in_usdc = 0
                
                # Calculate fee in USDC equivalent if we need to create an ATA
                if not receiver_account_exists:
                    # Get SOL/USD price
                    try:
                        sol_to_usdc = await fetch_sol_price_usd()
                        ata_fee_in_usdc = ATA_CREATION_FEE_SOL * sol_to_usdc
                        logger.info(f"Receiver needs ATA creation. Fee: {ATA_CREATION_FEE_SOL} SOL = {ata_fee_in_usdc:.6f} USDC")
                        
                        # Deduct the fee from the USDC amount
                        adjusted_amount_usdc = max(0, amount_usdc - ata_fee_in_usdc)
                        
                        # Check if amount is now too small to process
                        if adjusted_amount_usdc <= 0:
                            results.append((user_id, False, "", f"After ATA creation fee deduction ({ata_fee_in_usdc:.6f} USDC), the remaining amount would be zero or negative."))
                            continue
                        
                        logger.info(f"Adjusted USDC amount after fee deduction: {adjusted_amount_usdc} (original: {amount_usdc})")
                    except Exception as e:
                        logger.error(f"Error getting price data: {e}")
                        results.append((user_id, False, "", f"Error getting price data: {str(e)}"))
                        continue
                
                # Create associated token account instruction if needed
                if not receiver_account_exists:
                    create_ata_accounts = [
                        # 0. [signer, writable] Funding account
                        AccountMeta(pubkey=sender_pubkey, is_signer=True, is_writable=True),
                        # 1. [writable] Associated token account address to be created
                        AccountMeta(pubkey=receiver_token_account, is_signer=False, is_writable=True),
                        # 2. [] Wallet address for the new associated token account
                        AccountMeta(pubkey=receiver_pubkey, is_signer=False, is_writable=False),
                        # 3. [] The token mint for the new associated token account
                        AccountMeta(pubkey=USDC_MINT, is_signer=False, is_writable=False),
                        # 4. [] System program
                        AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
                        # 5. [] SPL Token program
                        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
                        # 6. [] Rent sysvar
                        AccountMeta(pubkey=SYSVAR_RENT_PUBKEY, is_signer=False, is_writable=False),
                    ]
                    
                    create_ata_ix = Instruction(
                        program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
                        accounts=create_ata_accounts,
                        data=bytes()  # No data needed for this instruction
                    )
                    
                    instructions.append(create_ata_ix)
                
                # Convert amount to token amount (USDC has 6 decimals)
                usdc_decimals = 6
                token_amount = int(adjusted_amount_usdc * (10 ** usdc_decimals))
                
                # Create token transfer instruction
                transfer_data = bytes([3]) + token_amount.to_bytes(8, byteorder="little")
                
                transfer_accounts = [
                    # 0. [writable] Source token account
                    AccountMeta(pubkey=sender_token_account, is_signer=False, is_writable=True),
                    # 1. [writable] Destination token account
                    AccountMeta(pubkey=receiver_token_account, is_signer=False, is_writable=True),
                    # 2. [signer] Owner of source account
                    AccountMeta(pubkey=sender_pubkey, is_signer=True, is_writable=False),
                ]
                
                transfer_ix = Instruction(
                    program_id=TOKEN_PROGRAM_ID,
                    accounts=transfer_accounts,
                    data=transfer_data
                )
                
                instructions.append(transfer_ix)
                
                # Track user in this batch for results
                batch_user_info.append({
                    "user_id": user_id,
                    "wallet_address": wallet_address,
                    "original_amount": original_amount_usdc,
                    "adjusted_amount": adjusted_amount_usdc,
                    "ata_fee": ata_fee_in_usdc,
                    "receiver_account_exists": receiver_account_exists
                })
            
            if not instructions:
                logger.warning("No valid instructions generated for batch")
                continue
                
            # Create and sign transaction
            message = Message.new_with_blockhash(
                instructions,
                sender_pubkey,
                recent_blockhash
            )
            transaction = Transaction([keypair], message, recent_blockhash)
            
            # Send transaction
            try:
                send_response = SOLANA_CLIENT.send_transaction(transaction)
                if not send_response.value:
                    error_msg = "Failed to send transaction"
                    for user_info in batch_user_info:
                        results.append((user_info["user_id"], False, "", error_msg))
                    continue
                        
                sig = send_response.value
                tx_signature = str(sig)
                
                logger.info(f"Sent batch transaction {tx_signature} with {len(current_batch)} payments")
                
                # Wait for confirmation
                transaction_confirmed = False
                for attempt in range(MAX_CONFIRMATION_ATTEMPTS):
                    try:
                        status_resp = SOLANA_CLIENT.get_signature_statuses([sig])
                        if not status_resp or not status_resp.value or not status_resp.value[0]:
                            logger.info(f"Transaction status not available yet, attempt {attempt + 1}/{MAX_CONFIRMATION_ATTEMPTS}")
                            await asyncio.sleep(CONFIRMATION_CHECK_INTERVAL)
                            continue
                            
                        status = status_resp.value[0]
                        if status:
                            # Check for errors
                            err = status.err
                            if err:
                                logger.error(f"Transaction failed: {err}")
                                error_msg = f"Transaction failed: {err}"
                                for user_info in batch_user_info:
                                    results.append((user_info["user_id"], False, "", error_msg))
                                break
                            
                            # Check confirmation status
                            conf_status = status.confirmation_status
                            
                            # Check if the transaction is finalized
                            is_finalized = False
                            if "Finalized" in str(conf_status) or conf_status == "finalized" or \
                               (hasattr(conf_status, 'value') and conf_status.value == 'finalized'):
                                is_finalized = True
                                
                            if is_finalized:
                                transaction_confirmed = True
                                # Record success for all users in this batch
                                for user_info in batch_user_info:
                                    fee_info = ""
                                    if not user_info["receiver_account_exists"]:
                                        fee_info = f" (ATA creation fee of {ATA_CREATION_FEE_SOL} SOL = {user_info['ata_fee']:.6f} USDC was deducted from original amount of {user_info['original_amount']})"
                                    
                                    success_message = f"Transaction successful{fee_info}"
                                    results.append((user_info["user_id"], True, tx_signature, success_message))
                                break
                    except Exception as e:
                        logger.error(f"Error checking transaction status: {e}")
                    
                    await asyncio.sleep(CONFIRMATION_CHECK_INTERVAL)
                
                # If we exhausted all attempts without confirmation
                if not transaction_confirmed:
                    for user_info in batch_user_info:
                        results.append((user_info["user_id"], False, "", "Transaction timed out waiting for confirmation"))
                
            except Exception as e:
                logger.error(f"Error sending transaction: {str(e)}")
                for user_info in batch_user_info:
                    results.append((user_info["user_id"], False, "", f"Transaction failed: {str(e)}"))
        
        return results
        
    except Exception as e:
        logger.error(f"Error processing batch payments: {str(e)}")
        # Return failed result for all payments in the batch
        return [(user_id, False, "", f"Batch processing failed: {str(e)}") for user_id, _, _ in payment_batch]

# Helper function to find associated token address
def find_associated_token_address(wallet: Pubkey, token_mint: Pubkey) -> Pubkey:
    """Find the associated token account address for a wallet and token mint."""
    TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    
    seeds = [
        bytes(wallet), 
        bytes(TOKEN_PROGRAM_ID), 
        bytes(token_mint)
    ]
    program_derived = Pubkey.find_program_address(
        seeds, ASSOCIATED_TOKEN_PROGRAM_ID
    )
    return program_derived[0]