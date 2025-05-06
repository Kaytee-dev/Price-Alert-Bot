

# --- Global Bot Configuration ---
#POLL_INTERVAL = 330  # seconds

# Main Bot details
BOT_TOKEN = "7645462301:AAGPzpLZ03ddKIzQb3ovADTWYMztD9cKGNY" 
# SUPER_ADMIN_ID = -4750674293  
POLL_INTERVAL = 305  # seconds

# Test Bot details
# BOT_TOKEN = "8120859286:AAFKrigrQnt9UEgOg-mewE2D18fT6KuKwus" 
# # SUPER_ADMIN_ID = -4710110042
# POLL_INTERVAL = 60  # seconds


SUPER_ADMIN_ID = 965551493

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

# Token data to display for list token and alltokens command
PAGE_SIZE = 3
PAGE_SIZE_ALL = 10

# Divider line
DIVIDER_LINE = "-" * 47

# Percentage reward given to referrer when their referred user upgrades
REFERRAL_PERCENTAGE = 0.05 # 5% of upgrade fee

# 📍 JSON file paths
DATA_DIR = "storage/data/"

TRACKED_TOKENS_FILE = f"{DATA_DIR}tracked_tokens.json"
SYMBOLS_FILE = f"{DATA_DIR}symbols.json"

USER_TRACKING_FILE = f"{DATA_DIR}user_tracking.json"
USER_STATUS_FILE = f"{DATA_DIR}user_status.json"

TOKEN_HISTORY_FILE = f"{DATA_DIR}token_history.json"
ACTIVE_TOKENS_FILE = f"{DATA_DIR}active_tokens.json"

ADMINS_FILE = f"{DATA_DIR}admins.json"

RESTART_FLAG_FILE = f"{DATA_DIR}restart_flag.json"
ACTIVE_RESTART_USERS_FILE = f"{DATA_DIR}active_restart_users.json"

TIERS_FILE = f"{DATA_DIR}user_tiers.json"

USER_THRESHOLDS_FILE = f"{DATA_DIR}user_threshold.json"
USER_EXPIRY_FILE = f"{DATA_DIR}user_expiry.json"

REFERRALS_FILE = f"{DATA_DIR}user_referral.json"
NOTIFY_DATA_FILE = f"{DATA_DIR}user_notify_data.json"

# Wallet list for users to make payment to
WALLET_POOL_FILE = f"{DATA_DIR}wallets_devnet.json" 

# Dictionary of wallet address and encrypted private key
WALLET_SECRETS_FILE = f"{DATA_DIR}wallets_secrets.json"

# Keeping track records of successful user payments
PAYMENT_LOGS_FILE = f"{DATA_DIR}payment_logs.json"

# Main bot wallet list to make withdrawals to
PAYOUT_WALLETS_FILE = f"{DATA_DIR}payout.json"


# === SOLANA CONFIG ===

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_FEE_LAMPORTS = 5000
MIN_BALANCE_FOR_RENT = 890880

#SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"
SOLANA_RPC = "https://api.devnet.solana.com"
SOL_DECIMALS = 9
SOL_PAYMENT_TOLERANCE = 0.001
SOLSCAN_BASE = "https://solscan.io/account/{}"
SOLSCAN_TX_BASE = "https://solscan.io/tx/{}"