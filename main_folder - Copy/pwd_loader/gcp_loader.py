# password_loader/gcp_loader.py
import google.auth # type: ignore
from google.cloud import secretmanager

def get_wallet_password() -> str:
    client = secretmanager.SecretManagerServiceClient()
    project_id = google.auth.default()[1]
    secret_name = f"projects/{project_id}/secrets/wallet-master-password/versions/latest"

    response = client.access_secret_version(request={"name": secret_name})
    return response.payload.data.decode("utf-8")
