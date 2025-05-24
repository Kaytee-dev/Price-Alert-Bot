import asyncio
import logging
from typing import Dict, List, Tuple, Any
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.api import Client
from config import SOLANA_RPC
from telegram import Message


logger = logging.getLogger(__name__)

async def validate_wallet_addresses(
        eligible_users: List[Tuple[str, Dict[str, Any]]],
        status_msg: Message
        ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, str]]]:
    valid_users = []
    invalid_users = []

    if not eligible_users:
        return valid_users, invalid_users

    client = Client(SOLANA_RPC)
    logger.info(f"Using RPC endpoint: {SOLANA_RPC}")

    BATCH_SIZE = 5
    MAX_CONCURRENT = 5
    REQUEST_TIMEOUT = 10  # seconds

    request_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

    async def validate_single_wallet(user_id: str, data: Dict[str, Any]):
        addr = data["wallet_address"]
        logger.debug(f"Validating wallet for user {user_id}: {addr}")

        # Basic format validation (fast, no RPC call)
        if not (32 <= len(addr) <= 44):
            logger.warning(f"Invalid wallet format for user {user_id}: {addr}")
            return (user_id, "Invalid wallet format"), None

        # Try to create a Pubkey object (fast, no RPC call)
        try:
            pubkey = Pubkey.from_string(addr)
        except Exception as e:
            logger.warning(f"Invalid base58 public key for user {user_id}: {addr} - {str(e)}")
            return (user_id, "Invalid base58 public key"), None

        # RPC call with timeout and concurrency control
        async with request_semaphore:
            try:
                # Use asyncio timeout to prevent hanging
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    logger.debug(f"Fetching account info for: {addr}")
                    #resp = client.get_account_info(pubkey)
                    resp = await asyncio.to_thread(client.get_account_info, pubkey)

                    logger.debug(f"RPC response for {addr}: {resp}")

                    if resp is None or resp.value is None:
                        logger.warning(f"Uninitialized address: {addr} — cannot determine owner. Rejecting to be safe.")
                        return (user_id, "Address is uninitialized and ownership can't be verified"), None

                    owner = str(resp.value.owner)
                    is_system_owned = owner == "11111111111111111111111111111111"
                    is_token_owned = owner == TOKEN_PROGRAM_ID
                    data_len = len(resp.value.data) if hasattr(resp.value.data, '__len__') else 0
                    is_executable = resp.value.executable

                    logger.debug(f"Wallet {addr} details: System owned: {is_system_owned}, Token owned: {is_token_owned}, Data len: {data_len}, Executable: {is_executable}")

                    if is_token_owned:
                        logger.warning(f"Address is a token mint or token account owned by the Token Program: {addr}")
                        return (user_id, "Address owned by Token Program - likely token or mint"), None

                    if is_system_owned and data_len == 0 and not is_executable:
                        logger.info(f"Valid initialized user wallet for user {user_id}: {addr}")
                        return None, (user_id, data)
                    else:
                        reason = "Not a user wallet address"
                        if not is_system_owned:
                            reason = f"Address owned by program {owner}, not System Program"
                        elif data_len > 0:
                            reason = f"Address has {data_len} bytes of data (user wallets have none)"
                        elif is_executable:
                            reason = "Address is executable (user wallets are not executable)"

                        logger.warning(f"Invalid wallet for user {user_id}: {addr} - {reason}")
                        return (user_id, reason), None

            except asyncio.TimeoutError:
                logger.error(f"Timeout validating wallet for user {user_id}: {addr}")
                return (user_id, "Validation timed out"), None
            except Exception as e:
                logger.error(f"Error validating wallet for user {user_id}: {addr} - {str(e)}", exc_info=True)
                return (user_id, f"Validation error: {str(e)}"), None

    logger.info(f"Starting validation of {len(eligible_users)} wallets")

    # Use asyncio.gather with return_exceptions=True to prevent one failure from stopping all validations
    tasks = []
    for user_id, data in eligible_users:
        tasks.append(validate_single_wallet(user_id, data))

    # Process in batches to avoid memory issues with too many simultaneous tasks
    for i in range(0, len(tasks), BATCH_SIZE):
        batch = tasks[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(tasks) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(f"Processing batch {batch_num}/{total_batches} with {len(batch)} wallets")
        results = await asyncio.gather(*batch, return_exceptions=True)

        batch_valid = 0
        batch_invalid = 0
        batch_errors = 0

        for result in results:
            if isinstance(result, Exception):
                batch_errors += 1
                logger.error(f"Validation task threw exception: {str(result)}")
                continue
            
            invalid_result, valid_result = result
            if invalid_result:
                invalid_users.append(invalid_result)
                batch_invalid += 1
            if valid_result:
                valid_users.append(valid_result)
                batch_valid += 1

        if i % (BATCH_SIZE * 5) == 0 or i + BATCH_SIZE >= len(eligible_users):
            await status_msg.edit_text(
                f"⏳ Validating wallets... {min(i + BATCH_SIZE, len(eligible_users))}/{len(eligible_users)} checked"
            )

        logger.info(f"Completed batch {batch_num}/{total_batches}: {batch_valid} valid, {batch_invalid} invalid, {batch_errors} errors")

    logger.info(f"Wallet validation complete: {len(valid_users)} valid, {len(invalid_users)} invalid")

    if invalid_users:
        logger.info("Invalid wallets details:")
        for user_id, reason in invalid_users:
            logger.info(f"  User {user_id}: {reason}")

    return valid_users, invalid_users

