#!/usr/bin/env python3
# test_usdc_withdrawal.py - A test script for USDC transfers on Solana devnet

import asyncio
import logging
import sys
from getpass import getpass
from solders.keypair import Keypair  # type: ignore
from base58 import b58decode
from test_usdc_a import process_single_payout
from telegram.ext import CallbackContext
from solders.pubkey import Pubkey  # type: ignore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("USDC_Withdrawal_Test")

class MockContext:
    """Mock context to simulate Telegram context for testing purposes"""
    def __init__(self):
        pass

async def main():
    print("=== USDC Withdrawal Test (Solana Devnet) ===")
    print("NOTE: This script operates on Solana devnet only!")
    print("Make sure your wallet has devnet USDC tokens.")
    
    # Get private key (b58 encoded)
    try:
        private_key = getpass("Enter sender's b58 private key: ")
        
        # Convert private key from b58 to bytes and create keypair
        try:
            private_key_bytes = b58decode(private_key)
            keypair = Keypair.from_bytes(private_key_bytes)
            sender_address = str(keypair.pubkey())
            print(f"Sender wallet address: {sender_address}")
        except Exception as e:
            logger.error(f"Error loading private key: {str(e)}")
            return
        
        # Get recipient address
        recipient_address = input("Enter recipient wallet address: ")
        
        # Validate the address format
        try:
            # from solders.pubkey import Pubkey
            Pubkey.from_string(recipient_address)
        except Exception as e:
            logger.error(f"Invalid recipient address format: {str(e)}")
            return
        
        # Get amount to send
        try:
            amount = float(input("Enter USDC amount to send: "))
            if amount <= 0:
                logger.error("Amount must be greater than 0")
                return
        except ValueError:
            logger.error("Invalid amount format. Please enter a valid number.")
            return
        
        # Create mock context
        mock_context = MockContext()
        
        # Confirm transaction
        print("\nTransaction details:")
        print(f"From: {sender_address}")
        print(f"To: {recipient_address}")
        print(f"Amount: {amount} USDC")
        confirmation = input("\nConfirm transaction? (y/n): ")
        
        if confirmation.lower() != 'y':
            print("Transaction cancelled")
            return
        
        print("\nInitiating transaction...")
        
        # Process the payment
        success, signature, message = await process_single_payout(
            user_id="test_user",
            wallet_address=recipient_address,
            amount_usdc=amount,
            keypair=keypair,
            context=mock_context
        )
        
        # Display results
        if success:
            print(f"\n✅ Transaction successful!")
            print(f"Transaction signature: {signature}")
            print(f"View on Solana Explorer: https://explorer.solana.com/tx/{signature}?cluster=devnet")
        else:
            print(f"\n❌ Transaction failed: {message}")
    
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())