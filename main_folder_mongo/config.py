

# --- Global Bot Configuration ---
#POLL_INTERVAL = 330  # seconds

# Main Bot details
# BOT_TOKEN = "7645462301:AAGPzpLZ03ddKIzQb3ovADTWYMztD9cKGNY" 
# # SUPER_ADMIN_ID = -4750674293  
# POLL_INTERVAL = 305  # seconds

# # Test Bot details
BOT_TOKEN = "8120859286:AAFKrigrQnt9UEgOg-mewE2D18fT6KuKwus" 
# SUPER_ADMIN_ID = -4710110042
POLL_INTERVAL = 60  # seconds

SUPER_ADMIN_ID = 965551493

# 📍 JSON file paths
DATA_DIR = "storage/data/"

# Bot logging details
BOT_TG_GROUP = "https://t.me/+f3Esd9E_VvQxMDU0"
BOT_NAME = "PumpCycle Bot"
BOT_LOGS_ID = -1002321684480
BOT_SPIKE_LOGS_ID = -1002321684480
BOT_PAYMENT_LOGS_ID = -1002639088331
BOT_ERROR_LOGS_ID = -1002505107844
BOT_REFERRAL_LOGS_ID = -1002607201258
BOT_INFO_LOGS_ID = -1002559903257

# 🔗 Base URL for token links
BASE_URL = "https://gmgn.ai/sol/token/"
DEXSCREENER_BASE = "https://dexscreener.com/"
DEXSCREENER_API_BASE = "https://api.dexscreener.com"


# Token data to display for list token and alltokens command
PAGE_SIZE = 3
PAGE_SIZE_ALL = 10

# Divider line
DIVIDER_LINE = "-" * 40

# Percentage reward given to referrer when their referred user upgrades
REFERRAL_PERCENTAGE = 0.05 # 5% of upgrade fee

# === SOLANA CONFIG ===
LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_FEE_LAMPORTS = 5000
MIN_BALANCE_FOR_RENT = 890880

#SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"
SOLANA_RPC = "https://api.devnet.solana.com"
#SOLANA_RPC = "https://mainnet.helius-rpc.com/?api-key=b7655961-b3fa-4d6c-9abe-28a6d201305f"
SOL_DECIMALS = 9
SOL_PAYMENT_TOLERANCE = 0.001
SOLSCAN_BASE = "https://solscan.io/account/{}"
SOLSCAN_TX_BASE = "https://solscan.io/tx/{}"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# Constants for the wallet listing pagination
LIST_WALLET_PAGE = "list_wallet_page"
WALLET_PAGE_SIZE = 5  # Default page size for wallet listings