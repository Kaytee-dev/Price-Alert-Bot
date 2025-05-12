import asyncio
import json
import logging
import os
import sys
from typing import Dict, List, Tuple, Any

# Import the validation function from the module
# Assuming the original code is in a file named wallet_validator.py
from main_folder.util.wallet_validator import validate_wallet_addresses

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("wallet_test")
# Get the directory of the current script
script_dir = os.path.dirname(os.path.abspath(__file__))

async def load_and_validate_wallets(json_file_path: str) -> None:
    """
    Load wallet addresses from a JSON file and validate them.
    
    Args:
        json_file_path: Path to the JSON file containing wallet addresses
    """
    logger.info(f"Loading wallet data from {json_file_path}")
    
    if not os.path.exists(json_file_path):
        logger.error(f"File not found: {json_file_path}")
        return
    
    try:
        # Load the JSON data
        with open(json_file_path, 'r') as file:
            wallet_data = json.load(file)
        
        # Format the data as expected by the validation function
        eligible_users: List[Tuple[str, Dict[str, Any]]] = []
        
        # Check if the JSON is in the expected format
        if isinstance(wallet_data, list):
            # If it's a list of objects with user_id and wallet_address
            for item in wallet_data:
                if isinstance(item, dict) and "user_id" in item and "wallet_address" in item:
                    user_id = item["user_id"]
                    wallet_address = item["wallet_address"]
                    eligible_users.append((user_id, {"wallet_address": wallet_address}))
                else:
                    logger.warning(f"Skipping invalid entry in JSON list: {item}")
        elif isinstance(wallet_data, dict):
            # If it's a dict with user_id as keys and wallet_address as values
            for user_id, user_data in wallet_data.items():
                if isinstance(user_data, dict) and "wallet_address" in user_data:
                    eligible_users.append((user_id, user_data))
                elif isinstance(user_data, str):
                    # If the value is just the wallet address string
                    eligible_users.append((user_id, {"wallet_address": user_data}))
                else:
                    logger.warning(f"Skipping invalid entry for user {user_id}: {user_data}")
        else:
            logger.error(f"Unexpected JSON format: {type(wallet_data)}")
            return
        
        logger.info(f"Loaded {len(eligible_users)} wallet addresses for validation")
        
        # Call the validation function
        valid_users, invalid_users = await validate_wallet_addresses(eligible_users)
        
        # Process results
        logger.info(f"Validation complete: {len(valid_users)} valid wallets, {len(invalid_users)} invalid wallets")
        
        # Print the results
        if valid_users:
            logger.info("Valid wallets:")
            for user_id, data in valid_users:
                logger.info(f"  User {user_id}: {data['wallet_address']}")
        
        if invalid_users:
            logger.info("Invalid wallets:")
            for user_id, reason in invalid_users:
                logger.info(f"  User {user_id}: {reason}")
        
        # Optionally save results to output files
        save_results_to_file(valid_users, invalid_users)
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON file: {e}")
    except Exception as e:
        logger.error(f"Error processing wallet data: {e}", exc_info=True)

def save_results_to_file(valid_users: List[Tuple[str, Dict[str, Any]]], 
                        invalid_users: List[Tuple[str, str]]) -> None:
    """
    Save validation results to JSON files.
    
    Args:
        valid_users: List of valid users with their data
        invalid_users: List of invalid users with reasons
    """
    # Save valid users
    valid_output = {
        user_id: data
        for user_id, data in valid_users
    }
    
    # Save invalid users
    invalid_output = {
        user_id: reason
        for user_id, reason in invalid_users
    }
    
    try:
        with open("valid_wallets.json", "w") as f:
            json.dump(valid_output, f, indent=2)
        logger.info(f"Valid wallet results saved to valid_wallets.json")
        
        with open("invalid_wallets.json", "w") as f:
            json.dump(invalid_output, f, indent=2)
        logger.info(f"Invalid wallet results saved to invalid_wallets.json")
    except Exception as e:
        logger.error(f"Error saving results to file: {e}")

async def main():
    """Main function to run the wallet validation test."""
    # Get the JSON file path from command line or use a default
    json_file_path = sys.argv[1] if len(sys.argv) > 1 else "wallets.json"
    
    logger.info("Starting wallet validation test")
    await load_and_validate_wallets(json_file_path)
    logger.info("Wallet validation test completed")

if __name__ == "__main__":
    asyncio.run(main())