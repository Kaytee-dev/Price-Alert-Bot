# test_withdrawal.py

import time
from solana.rpc.api import Client
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.system_program import transfer, TransferParams
from solders.message import Message # type: ignore
from solders.transaction import Transaction # type: ignore
from base58 import b58decode

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_FEE_LAMPORTS = 5000
SOLANA_CLIENT = Client("https://api.devnet.solana.com")


def send_sol(from_secret: str, to_address: str, amount_sol: float):
    try:
        from_keypair = Keypair.from_bytes(b58decode(from_secret))
        to_pubkey = Pubkey.from_string(to_address)
        lamports = int(amount_sol * LAMPORTS_PER_SOL)

        # Check balance
        balance = SOLANA_CLIENT.get_balance(from_keypair.pubkey()).value
        if balance < lamports + (DEFAULT_FEE_LAMPORTS * 2):
            print(f"❌ Insufficient balance: {balance} lamports")
            return

        # Get recent blockhash
        recent_blockhash = SOLANA_CLIENT.get_latest_blockhash().value.blockhash

        # Create transfer instruction
        transfer_instruction = transfer(TransferParams(
            from_pubkey=from_keypair.pubkey(),
            to_pubkey=to_pubkey,
            lamports=lamports
        ))

        # Create message and transaction
        message = Message.new_with_blockhash(
            [transfer_instruction],
            from_keypair.pubkey(),
            recent_blockhash
        )
        txn = Transaction([from_keypair], message, recent_blockhash)

        # Send transaction
        sig = SOLANA_CLIENT.send_transaction(txn).value
        print(f"✅ Transaction submitted: {sig}")
        print(f"🔗 View on explorer: https://explorer.solana.com/tx/{sig}?cluster=devnet")

        # Status confirmation
        print("⏳ Awaiting confirmation...")
        for _ in range(10):
            status_resp = SOLANA_CLIENT.get_signature_statuses([sig])
            status = status_resp.value[0]
            if status:
                conf_status = status.confirmation_status
                err = status.err
                if err:
                    print(f"❌ Transaction failed with error: {err}")
                    return
                print(f"✅ Confirmation status: {conf_status}")
                if conf_status == "finalized":
                    print("✅ Transaction finalized.")
                    return
            time.sleep(2)

        print("⚠️ Transaction not finalized after waiting.")

    except Exception as e:
        print(f"❌ Error sending SOL: {e}")


if __name__ == "__main__":
    from_key = input("Enter FROM wallet private key (base58): ").strip()
    to_address = input("Enter TO wallet address: ").strip()
    amount = float(input("Enter amount in SOL: "))

    send_sol(from_key, to_address, amount)
