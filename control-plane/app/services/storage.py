import logging
import os
import json
from typing import Optional

logger = logging.getLogger(__name__)

# File path for the local persistent mock in development
MOCK_STORAGE_FILE = os.getenv("AOS_MOCK_STORAGE_FILE") or os.path.join(os.path.dirname(__file__), "../../scratch/mock_storage.json")

class GcsClient:
    """Wrapper for Google Cloud Storage, falling back to a local persistent JSON mock in development/testing."""

    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT", "aos-control-plane")
        self._client = None
        self._gcs_init_failed = False
        
        # Try to initialize real GCP client if not in test environment and credentials exist
        if os.getenv("AOS_ENV") != "test" and "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            try:
                from google.cloud import storage
                self._client = storage.Client(project=self.project_id)
                logger.info("Initialized Google Cloud Storage client")
            except ImportError:
                logger.warning("google-cloud-storage not installed. Falling back to local JSON mock.")
            except Exception as e:
                logger.error(f"Failed to initialize real GCS client: {e}. GCS operations will be degraded.")
                self._gcs_init_failed = True

    def _load_mock_storage(self) -> dict:
        if os.path.exists(MOCK_STORAGE_FILE):
            try:
                with open(MOCK_STORAGE_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load mock storage: {e}")
                return {}
        return {}

    def _save_mock_storage(self, data: dict):
        os.makedirs(os.path.dirname(MOCK_STORAGE_FILE), exist_ok=True)
        try:
            with open(MOCK_STORAGE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save mock storage: {e}")

    @classmethod
    def clear(cls):
        """Clears all mock storage objects in the local registry."""
        if os.path.exists(MOCK_STORAGE_FILE):
            try:
                os.remove(MOCK_STORAGE_FILE)
            except Exception:
                pass

    async def upload_from_string(self, bucket_name: str, blob_path: str, content: str) -> bool:
        """Uploads a string content to a GCS blob."""
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                blob.upload_from_string(content)
                logger.info(f"Successfully uploaded gs://{bucket_name}/{blob_path} to GCP GCS")
                return True
            except Exception as e:
                logger.error(f"Real GCS upload failed: {e}")
                raise e

        if self._gcs_init_failed:
            raise RuntimeError(f"GCS client failed to initialize — upload of gs://{bucket_name}/{blob_path} cannot proceed")

        # Local JSON Mock Write (test / no-credentials dev mode only)
        storage_data = self._load_mock_storage()
        key = f"gs://{bucket_name}/{blob_path}"
        storage_data[key] = content
        self._save_mock_storage(storage_data)
        logger.info(f"Mock wrote blob gs://{bucket_name}/{blob_path} to local registry")
        return True

    async def download_as_string(self, bucket_name: str, blob_path: str) -> Optional[str]:
        """Downloads a GCS blob as a string."""
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                if blob.exists():
                    return blob.download_as_text()
                return None
            except Exception as e:
                logger.error(f"Real GCS download failed: {e}")
                raise e

        if self._gcs_init_failed:
            raise RuntimeError(f"GCS client failed to initialize — download of gs://{bucket_name}/{blob_path} cannot proceed")

        # Local JSON Mock Read
        storage_data = self._load_mock_storage()
        key = f"gs://{bucket_name}/{blob_path}"
        return storage_data.get(key)

    async def delete_blob(self, bucket_name: str, blob_path: str) -> bool:
        """Deletes a blob from a GCS bucket."""
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                if blob.exists():
                    blob.delete()
                    logger.info(f"Successfully deleted gs://{bucket_name}/{blob_path} from GCP GCS")
                    return True
                return False
            except Exception as e:
                logger.error(f"Real GCS delete failed: {e}")
                raise e

        if self._gcs_init_failed:
            raise RuntimeError(f"GCS client failed to initialize — delete of gs://{bucket_name}/{blob_path} cannot proceed")

        # Local JSON Mock Delete
        storage_data = self._load_mock_storage()
        key = f"gs://{bucket_name}/{blob_path}"
        if key in storage_data:
            del storage_data[key]
            self._save_mock_storage(storage_data)
            logger.info(f"Mock deleted gs://{bucket_name}/{blob_path} from local registry")
            return True
        return False

    async def blob_exists(self, bucket_name: str, blob_path: str) -> bool:
        """Checks if a blob exists in a GCS bucket."""
        if self._client:
            try:
                bucket = self._client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                return blob.exists()
            except Exception as e:
                logger.error(f"Real GCS blob check failed: {e}")
                raise e

        if self._gcs_init_failed:
            raise RuntimeError(f"GCS client failed to initialize — exists check for gs://{bucket_name}/{blob_path} cannot proceed")

        # Local JSON Mock Check
        storage_data = self._load_mock_storage()
        key = f"gs://{bucket_name}/{blob_path}"
        return key in storage_data
