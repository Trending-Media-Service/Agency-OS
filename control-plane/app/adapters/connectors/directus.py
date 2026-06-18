import logging
import httpx
from typing import Any
from .base import register_connector

logger = logging.getLogger(__name__)

@register_connector
class DirectusConnector:
    provider = "directus"

    def __init__(self, token: str, config: dict[str, Any]):
        self.token = token # Expecting static admin API token
        self.config = config
        self.url = config.get("url", "http://localhost:8055")
        
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def verify_connection(self) -> bool:
        """Verifies Directus connection by querying server info or self profile."""
        if not self.token or self.token == "mock-directus-secret":
            logger.info("[Mock Directus] Verifying connection successfully")
            return True

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{self.url}/users/me", headers=self.headers)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Directus connection verification failed: {e}")
                return False

    async def fetch_collection(self, collection_name: str) -> list[dict]:
        """Fetches items from a Directus collection."""
        if not self.token or self.token == "mock-directus-secret":
            logger.info(f"[Mock Directus] Fetched items from collection {collection_name}")
            return [{"id": 1, "title": "Mock Post 1"}, {"id": 2, "title": "Mock Post 2"}]

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.url}/items/{collection_name}", headers=self.headers)
            resp.raise_for_status()
            return resp.json().get("data", [])
