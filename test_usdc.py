 # Required solders imports for SPL token operations
from solders.pubkey import Pubkey  # type: ignore
from solders.instruction import Instruction, AccountMeta  # type: ignore
from solders.transaction import Transaction  # type: ignore
from solders.message import Message  # type: ignore
from solders.keypair import Keypair  # type: ignore

import logging
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
import asyncio


# Add constants from withdrawal.py
MAX_CONFIRMATION_ATTEMPTS = 20
CONFIRMATION_CHECK_INTERVAL = 3  # seconds

# Initialize Solana client like in withdrawal.py
from solana.rpc.api import Client
SOLANA_CLIENT = Client("https://api.devnet.solana.com")

async def process_single_payout(
    user_id: str, 
    wallet_address: str, 
    amount_usdc: float,
    keypair: Keypair,
    context: ContextTypes.DEFAULT_TYPE
) -> Tuple[bool, str, str]:
    try:
        logging.info(f"Processing USDC payment of {amount_usdc} to {wallet_address} for user {user_id}")
        
        
        # SPL Token Program ID
        TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
        SYSVAR_RENT_PUBKEY = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
        
        # USDC mint address (mainnet)
        #USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        
        # USDC mint address (devnet)
        USDC_MINT = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")

        
        # Convert amount to token amount (USDC has 6 decimals)
        usdc_decimals = 6
        token_amount = int(amount_usdc * (10 ** usdc_decimals))
        
        # Get sender and receiver public keys
        sender_pubkey = keypair.pubkey()
        receiver_pubkey = Pubkey.from_string(wallet_address)
        
        # Helper function to find associated token address
        def find_associated_token_address(wallet: Pubkey, token_mint: Pubkey) -> Pubkey:
            """Find the associated token account address for a wallet and token mint."""
            seeds = [
                bytes(wallet), 
                bytes(TOKEN_PROGRAM_ID), 
                bytes(token_mint)
            ]
            program_derived = Pubkey.find_program_address(
                seeds, ASSOCIATED_TOKEN_PROGRAM_ID
            )
            return program_derived[0]
        
        # Get token accounts for sender and receiver
        sender_token_account = find_associated_token_address(sender_pubkey, USDC_MINT)
        receiver_token_account = find_associated_token_address(receiver_pubkey, USDC_MINT)
        
        # Check if receiver's token account exists
        account_info_response = SOLANA_CLIENT.get_account_info(receiver_token_account)
        receiver_account_exists = account_info_response.value is not None
        
        # Prepare instructions
        instructions = []
        
        # Create associated token account instruction if needed
        if not receiver_account_exists:
            logging.info(f"Creating token account for recipient {wallet_address}")
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
            
            # Create instruction with empty data (the program knows what to do based on accounts)
            create_ata_ix = Instruction(
                program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
                accounts=create_ata_accounts,
                data=bytes()  # No data needed for this instruction
            )
            
            instructions.append(create_ata_ix)
        
        # Create token transfer instruction
        # Command is 3 (transfer) followed by amount as a little-endian 64-bit integer
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
        
        # Build transaction
        blockhash_response = SOLANA_CLIENT.get_latest_blockhash()
        if not blockhash_response.value:
            return False, "", "Failed to get latest blockhash"
            
        recent_blockhash = blockhash_response.value.blockhash
        
        # Create and sign transaction
        message = Message.new_with_blockhash(
            instructions,
            sender_pubkey,
            recent_blockhash
        )
        transaction = Transaction([keypair], message, recent_blockhash)
        
        # Send transaction
        send_response = SOLANA_CLIENT.send_transaction(transaction)
        if not send_response.value:
            return False, "", "Failed to send transaction"
                
        sig = send_response.value
        tx_signature = str(sig)
        logging.info(f"Sent USDC transaction {tx_signature}")
        
        # Confirm transaction
        for attempt in range(MAX_CONFIRMATION_ATTEMPTS):
            try:
                status_resp = SOLANA_CLIENT.get_signature_statuses([sig])
                if not status_resp or not status_resp.value or not status_resp.value[0]:
                    logging.info(f"Transaction status not available yet, attempt {attempt + 1}/{MAX_CONFIRMATION_ATTEMPTS}")
                    await asyncio.sleep(CONFIRMATION_CHECK_INTERVAL)
                    continue
                    
                status = status_resp.value[0]
                if status:
                    # Check for errors
                    err = status.err
                    if err:
                        logging.error(f"Transaction failed: {err}")
                        return False, "", f"Transaction failed: {err}"
                    
                    # Check confirmation status
                    conf_status = status.confirmation_status
                    
                    # Check if the transaction is finalized
                    is_finalized = False
                    if "Finalized" in str(conf_status) or conf_status == "finalized" or \
                       (hasattr(conf_status, 'value') and conf_status.value == 'finalized'):
                        is_finalized = True
                        
                    if is_finalized:
                        return True, tx_signature, "Transaction successful"
            except Exception as e:
                logging.error(f"Error checking transaction status: {e}")
            
            await asyncio.sleep(CONFIRMATION_CHECK_INTERVAL)
        
        return False, "", "Transaction timed out waiting for confirmation"
        
    except Exception as e:
        logging.error(f"Error processing USDC payment for {user_id}: {str(e)}")
        return False, "", f"Transaction failed: {str(e)}"