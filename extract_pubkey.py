# extract_pubkey.py

import base58
from solders.keypair import Keypair # type: ignore


def extract_public_key(base58_secret: str) -> str:
    try:
        secret_bytes = base58.b58decode(base58_secret)
        keypair = Keypair.from_bytes(secret_bytes)
        return str(keypair.pubkey())
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    test_input = input("Paste your 88-char base58 private key: ")
    print("Public Key:", extract_public_key(test_input))
