#!/usr/bin/env python3
"""
Solana Wallet Address Validator

This script validates Solana addresses to determine if they are user wallet addresses,
token/mint addresses, or program addresses.
"""

import argparse
import sys
from typing import Union, Dict, Any

from solders.pubkey import Pubkey # type: ignore
from solana.rpc.api import Client
from solders.rpc.responses import GetAccountInfoResp # type: ignore
# Removed import of solders.rpc.config and solders.rpc.responses as we're using dict approach


# Only keeping essential constant
SYSTEM_PROGRAM = "11111111111111111111111111111111"

# Maximum account size for a system owned account to be considered a user wallet
MAX_USER_WALLET_DATA_SIZE = 0  # User wallets have no data


def is_valid_pubkey(address: str) -> bool:
    """Check if the string is a valid Solana public key."""
    try:
        Pubkey.from_string(address)
        return True
    except ValueError:
        return False


def get_account_info(address: str, rpc_url: str = "https://api.devnet.solana.com") -> Union[Dict[str, Any], None]:
    """Fetch account information for the given address."""
    try:
        client = Client(rpc_url)
        pubkey = Pubkey.from_string(address)
        
        # Get account info using the object-oriented approach
        resp = client.get_account_info(pubkey)
        
        if resp is None or resp.value is None:
            # Account doesn't exist yet or has no SOL
            return None
            
        return {
            "executable": resp.value.executable,
            "owner": str(resp.value.owner),
            "lamports": resp.value.lamports,
            "data_len": len(resp.value.data) if hasattr(resp.value.data, '__len__') else 0,
            "rentEpoch": resp.value.rent_epoch,
        }
    except Exception as e:
        print(f"Error getting account info: {e}", file=sys.stderr)
        return None


def validate_address(address: str, rpc_url: str = "https://api.devnet.solana.com") -> Dict[str, Any]:
    """
    Validate if a Solana address is a user wallet address.
    
    Returns a dictionary with validation results.
    """
    result = {
        "address": address,
        "is_valid_pubkey": False,
        "exists_on_chain": False,
        "is_user_wallet": False,
        "details": {},
    }
    
    # Check if the address is a valid Solana public key
    if not is_valid_pubkey(address):
        result["details"]["error"] = "Invalid Solana address format"
        return result
    
    result["is_valid_pubkey"] = True
    
    # Get account info from RPC
    account_info = get_account_info(address, rpc_url)
    
    if account_info is None:
        # Account doesn't exist yet - could be a user wallet that hasn't been initialized
        result["is_user_wallet"] = True  # Uninitialized addresses can be user wallets
        result["details"]["message"] = "Address is valid but not yet initialized on-chain"
        return result
    
    result["exists_on_chain"] = True
    result["details"]["account_info"] = account_info
    
    # A user wallet is owned by the System Program and has no data
    if (account_info["owner"] == "11111111111111111111111111111111" and 
            account_info["data_len"] == MAX_USER_WALLET_DATA_SIZE and 
            not account_info["executable"]):
        result["is_user_wallet"] = True
    else:
        result["is_user_wallet"] = False
        result["details"]["message"] = "Not a user wallet (owned by another program or has data)"
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Validate if an address is a Solana user wallet")
    parser.add_argument("address", help="Solana address to validate")
    parser.add_argument("--rpc", default="https://api.mainnet-beta.solana.com", 
                        help="Solana RPC URL (default: https://api.mainnet-beta.solana.com)")
    args = parser.parse_args()
    
    try:
        result = validate_address(args.address, args.rpc)
        
        print(f"\nAddress: {result['address']}")
        print(f"Valid Pubkey: {'Yes' if result['is_valid_pubkey'] else 'No'}")
        print(f"Exists On-chain: {'Yes' if result['exists_on_chain'] else 'No'}")
        print(f"Is User Wallet: {'Yes' if result['is_user_wallet'] else 'No'}")
        
        if result["is_user_wallet"]:
            if result["exists_on_chain"]:
                print("\nThis is a valid user wallet address.")
            else:
                print("\nThis is a valid but uninitialized user wallet address.")
        else:
            print("\nThis is NOT a user wallet address.")
        
        # Print additional details if available
        if "account_info" in result["details"]:
            info = result["details"]["account_info"]
            print("\nAccount Details:")
            print(f"  SOL Balance: {info['lamports'] / 1_000_000_000:.9f} SOL")
            print(f"  Owner: {info['owner']}")
            print(f"  Data Size: {info['data_len']} bytes")
            print(f"  Executable: {'Yes' if info['executable'] else 'No'}")
        
        if "message" in result["details"]:
            print(f"\nNote: {result['details']['message']}")
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()