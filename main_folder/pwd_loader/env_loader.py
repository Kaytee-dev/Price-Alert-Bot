# password_loader/env_loader.py
import os
from dotenv import load_dotenv

load_dotenv()

def get_wallet_password() -> str:
    password = os.getenv("WALLET_MASTER_PASSWORD")
    if not password:
        raise RuntimeError("WALLET_MASTER_PASSWORD not set in .env")
    return password
