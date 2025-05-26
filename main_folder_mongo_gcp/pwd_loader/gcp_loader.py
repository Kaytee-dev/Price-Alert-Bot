# password_loader/gcp_loader.py
import google.auth # type: ignore
from google.cloud import secretmanager
from typing import Optional

def get_wallet_password() -> str:
    client = secretmanager.SecretManagerServiceClient()
    project_id = google.auth.default()[1]
    secret_name = f"projects/{project_id}/secrets/wallet-master-password/versions/latest"

    response = client.access_secret_version(request={"name": secret_name})
    return response.payload.data.decode("utf-8")

_client = secretmanager.SecretManagerServiceClient()

def _get_project_id() -> str:
    return google.auth.default()[1]

def get_secret(name: str, version: str = "latest") -> Optional[str]:
    try:
        project_id = _get_project_id()
        path = f"projects/{project_id}/secrets/{name}/versions/{version}"
        response = _client.access_secret_version(request={"name": path})
        return response.payload.data.decode("utf-8")
    except Exception as e:
        print(f"[SecretManager] Failed to fetch {name}: {e}")
        return None