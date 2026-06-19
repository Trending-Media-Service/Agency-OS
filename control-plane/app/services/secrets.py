import logging
import os
import json

logger = logging.getLogger(__name__)

# File path for the local persistent mock in development
MOCK_SECRETS_FILE = os.path.join(os.path.dirname(__file__), "../../scratch/mock_secrets.json")

class SecretManagerClient:
    """Wrapper for Google Cloud Secret Manager, falling back to a local persistent JSON mock in development."""

    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT", "aos-control-plane")
        self._client = None
        
        # Try to initialize real GCP client if not in test environment and credentials exist
        if os.getenv("AOS_ENV") != "test" and "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            try:
                from google.cloud import secretmanager
                self._client = secretmanager.SecretManagerServiceClient()
                logger.info("Initialized Google Cloud Secret Manager client")
            except ImportError:
                logger.warning("google-cloud-secret-manager not installed. Falling back to local JSON mock.")
            except Exception as e:
                logger.error(f"Failed to initialize real Secret Manager client: {e}. Falling back to local JSON mock.")

    def _load_mock_secrets(self) -> dict:
        if os.path.exists(MOCK_SECRETS_FILE):
            try:
                with open(MOCK_SECRETS_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load mock secrets: {e}")
                return {}
        return {}

    def _save_mock_secrets(self, data: dict):
        os.makedirs(os.path.dirname(MOCK_SECRETS_FILE), exist_ok=True)
        try:
            with open(MOCK_SECRETS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save mock secrets: {e}")

    @classmethod
    def clear(cls):
        """Clears all mock secrets in the local registry."""
        if os.path.exists(MOCK_SECRETS_FILE):
            try:
                os.remove(MOCK_SECRETS_FILE)
            except Exception:
                pass

    async def write_secret(self, secret_id: str, value: str) -> str:
        """Writes/Creates a secret version.
        
        Returns the resource path reference (secret_ref).
        """
        if value is None:
            raise ValueError("Secret value cannot be None")
        if not isinstance(value, str):
            raise TypeError("Secret value must be a string")
        if value.startswith("projects/") and "/secrets/" in value:
            logger.info(f"Value is already a Secret Manager reference: {value}. Returning as-is.")
            return value
        if self._client:
            try:
                # Real GCP Secret Manager call
                parent = f"projects/{self.project_id}"
                secret_path = f"{parent}/secrets/{secret_id}"
                
                # Check if secret exists first, create if not
                try:
                    self._client.get_secret(name=secret_path)
                except Exception:
                    # Create secret
                    self._client.create_secret(
                        parent=parent,
                        secret_id=secret_id,
                        secret={"replication": {"automatic": {}}}
                    )
                
                # Add version
                response = self._client.add_secret_version(
                    parent=secret_path,
                    payload={"data": value.encode("utf-8")}
                )
                logger.info(f"Successfully wrote secret version {response.name} to GCP")
                return response.name
            except Exception as e:
                logger.error(f"Real Secret Manager write failed: {e}. Falling back to mock.")

        # Local JSON Mock Write
        secrets = self._load_mock_secrets()
        ref = f"projects/{self.project_id}/secrets/{secret_id}/versions/latest"
        secrets[ref] = value
        self._save_mock_secrets(secrets)
        logger.info(f"Mock wrote secret {secret_id} to local registry: {ref}")
        return ref

    async def read_secret(self, secret_ref: str) -> str:
        """Reads a secret version by its reference."""
        if self._client:
            try:
                # Real GCP Secret Manager read
                response = self._client.access_secret_version(name=secret_ref)
                return response.payload.data.decode("utf-8")
            except Exception as e:
                logger.error(f"Real Secret Manager read failed: {e}. Falling back to mock.")

        # Local JSON Mock Read
        secrets = self._load_mock_secrets()
        val = secrets.get(secret_ref)
        if val is None:
            # Try to resolve fuzzy match (e.g. without version)
            prefix = secret_ref.split("/versions/")[0]
            for k, v in secrets.items():
                if k.startswith(prefix):
                    return v
            raise ValueError(f"Secret not found in mock registry: {secret_ref}")
        return val

    async def delete_secret(self, secret_ref: str):
        """Deletes a secret by its reference."""
        if self._client:
            try:
                # Real GCP Secret Manager delete
                secret_path = secret_ref.split("/versions/")[0]
                self._client.delete_secret(name=secret_path)
                logger.info(f"Successfully deleted secret {secret_path} from GCP")
                return
            except Exception as e:
                logger.error(f"Real Secret Manager delete failed: {e}. Falling back to mock.")

        # Local JSON Mock Delete
        secrets = self._load_mock_secrets()
        if secret_ref in secrets:
            del secrets[secret_ref]
            self._save_mock_secrets(secrets)
            logger.info(f"Mock deleted secret version {secret_ref} from local registry")
        else:
            # Fuzzy match delete
            prefix = secret_ref.split("/versions/")[0]
            to_del = [k for k in secrets if k.startswith(prefix)]
            for k in to_del:
                del secrets[k]
            if to_del:
                self._save_mock_secrets(secrets)
                logger.info(f"Mock deleted {len(to_del)} secrets matching prefix {prefix}")
