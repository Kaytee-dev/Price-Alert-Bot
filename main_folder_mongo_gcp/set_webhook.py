import requests
from pwd_loader.gcp_loader import get_secret

BOT_TOKEN = get_secret("bot-token")
WEBHOOK_PATH = get_secret("webhook-path")  # e.g. /webhook/abc123
CLOUDRUN_URL = get_secret("cloudrun-url")  # e.g. https://my-bot-service-abc123.a.run.app

assert BOT_TOKEN and WEBHOOK_PATH and CLOUDRUN_URL, "Missing required secrets."

# Build the full webhook URL
webhook_url = f"{CLOUDRUN_URL}{WEBHOOK_PATH}"

response = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    data={"url": webhook_url}
)

print("Webhook set:", response.json())
