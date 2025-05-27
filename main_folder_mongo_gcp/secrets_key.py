# wallet_secrets.py

import base64
import logging
from typing import Dict, Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

import storage.payment_collection as payment_collection
from pwd_loader.gcp_loader import get_wallet_password, get_secret

# === CONFIG ===
#SALT = b"solana-secure-wallet-salt" # Static salt (should be secret in prod)

ITERATIONS = 390000

# === In-memory cache of decrypted wallets ===
DECRYPTED_WALLETS: Dict[str, str] = {}

logger = logging.getLogger(__name__)


def derive_key(password: str) -> bytes:
    print(f"🌐 Password: {password}")
    SALT = get_secret("salt").encode("utf-8")
    print(f"🌐 SALT: {SALT}")
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=ITERATIONS,
        backend=default_backend()
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def is_encrypted_value(value: str) -> bool:
    return value.startswith("gAAAA") and len(value) > 80


async def load_encrypted_keys() -> Dict[str, str]:
    """
    Loads and decrypts wallet secrets from MongoDB, populates DECRYPTED_WALLETS.
    """
    global DECRYPTED_WALLETS

    secrets = payment_collection.PAYMENT_COLLECTION.get("wallet_secrets", {}).get("secrets", {})
    password = get_wallet_password()
    key = derive_key(password)
    fernet = Fernet(key)

    decrypted_keys = {}
    modified = False
    updated_secrets = dict(secrets)

    for address, stored_value in secrets.items():
        try:
            if not is_encrypted_value(stored_value):
                logger.warning(f"⚠️ Wallet {address} contains an unencrypted key; encrypting it now.")
                encrypted_value = encrypt_key(stored_value, password)
                updated_secrets[address] = encrypted_value
                stored_value = encrypted_value
                modified = True

            decrypted = fernet.decrypt(stored_value.encode()).decode()
            decrypted_keys[address] = decrypted

        except InvalidToken:
            logger.warning(f"⚠️ Invalid decryption token for wallet {address}")
        except Exception as e:
            logger.error(f"❌ Error decrypting wallet {address}: {e}")

    # Save updated secrets if we re-encrypted anything
    if modified:
        await persist_encrypted_keys(updated_secrets)

    DECRYPTED_WALLETS = decrypted_keys

    logger.info("✅ WALLET SECRETS loaded and formatted from database")
    return decrypted_keys


async def persist_encrypted_keys(secrets: Dict[str, str]):
    """
    Save encrypted keys back to MongoDB and sync cache.
    """
    collection = payment_collection.get_payments_collection()
    await collection.update_one(
        {"_id": "wallet_secrets"},
        {"$set": {"secrets": secrets}},
        upsert=True
    )
    payment_collection.PAYMENT_COLLECTION["wallet_secrets"] = {"_id": "wallet_secrets", "secrets": secrets}


def get_decrypted_wallet(address: str) -> Optional[str]:
    return DECRYPTED_WALLETS.get(address)


def decrypt_key(encrypted: str, password: str) -> str:
    key = derive_key(password)
    fernet = Fernet(key)
    return fernet.decrypt(encrypted.encode()).decode()


def encrypt_key(plain_key: str, password: str) -> str:
    key = derive_key(password)
    fernet = Fernet(key)
    return fernet.encrypt(plain_key.encode()).decode()
