import json
import base64
import logging
from typing import Dict, Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

from util.utils import load_json, save_json
from config import WALLET_SECRETS_FILE
from pwd_loader.env_loader import get_wallet_password


# === CONFIG ===
SALT = b"solana-secure-wallet-salt"  # Static salt (should be secret in prod)
ITERATIONS = 390000

# === In-memory cache of decrypted wallets ===
DECRYPTED_WALLETS: Dict[str, str] = {}

logger = logging.getLogger(__name__)

# === KDF to derive encryption key from password ===
def derive_key(password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=ITERATIONS,
        backend=default_backend()
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def is_encrypted_value(value: str) -> bool:
    return value.startswith("gAAAA") and len(value) > 80

# === Load and decrypt entire secret wallet file ===
def load_encrypted_keys() -> Dict[str, str]:
    global DECRYPTED_WALLETS
    encrypted_data = load_json(WALLET_SECRETS_FILE, {}, "wallet secrets")

    password = get_wallet_password()
    key = derive_key(password)
    fernet = Fernet(key)

    decrypted_keys = {}
    modified = False

    for address, stored_value in encrypted_data.items():
        try:
            if not is_encrypted_value(stored_value):
                logger.warning(f"⚠️ Wallet {address} contains an unencrypted key; encrypting it now.")
                encrypted_value = encrypt_key(stored_value, password)
                encrypted_data[address] = encrypted_value
                stored_value = encrypted_value
                modified = True

            decrypted = fernet.decrypt(stored_value.encode()).decode()
            decrypted_keys[address] = decrypted

        except InvalidToken:
            logger.warning(f"⚠️ Invalid decryption token for wallet {address}")
        except Exception as e:
            logger.error(f"❌ Error decrypting wallet {address}: {e}")

    if modified:
        save_json(WALLET_SECRETS_FILE, encrypted_data, "wallet secrets")

    DECRYPTED_WALLETS = decrypted_keys
    return decrypted_keys

# === Save encrypted keys and sync in-memory + wallet list ===
# def save_encrypted_keys(data: Dict[str, str], file_path: str, password: str):
#     save_json(file_path, data, "wallet secrets")
    
def persist_encrypted_keys(data: Dict[str, str]):
    save_json(WALLET_SECRETS_FILE, data, "wallet secrets")


# === Access decrypted key by address ===
def get_decrypted_wallet(address: str) -> Optional[str]:
    return DECRYPTED_WALLETS.get(address)

# === Decrypt one key from memory ===
def decrypt_key(encrypted: str, password: str) -> str:
    key = derive_key(password)
    fernet = Fernet(key)
    return fernet.decrypt(encrypted.encode()).decode()

def encrypt_key(plain_key: str, password: str) -> str:
    key = derive_key(password)
    fernet = Fernet(key)
    return fernet.encrypt(plain_key.encode()).decode()
