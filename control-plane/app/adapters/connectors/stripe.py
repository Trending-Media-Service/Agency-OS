import logging
import httpx
from typing import Any
from .base import register_connector

logger = logging.getLogger(__name__)

@register_connector
class StripeConnector:
    provider = "stripe"

    def __init__(self, token: str, config: dict[str, Any]):
        self.token = token
        self.config = config
        self.api_url = config.get("api_url", "https://api.stripe.com/v1")
        # Initialize client
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Stripe-Version": "2023-10-16"
        }

    async def verify_connection(self) -> bool:
        """Verifies Stripe secret key is valid by fetching account details."""
        if not self.token or self.token == "mock-stripe-secret":
            logger.info("[Mock Stripe] Verifying connection successfully")
            return True

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{self.api_url}/accounts", headers=self.headers)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Stripe connection verification failed: {e}")
                return False

    async def create_charge(self, amount_minor: int, currency: str, description: str) -> dict:
        """Creates a charge on Stripe."""
        if not self.token or self.token == "mock-stripe-secret":
            logger.info(f"[Mock Stripe] Charged {amount_minor} {currency}: {description}")
            return {"id": "ch_mock_12345", "amount": amount_minor, "currency": currency, "status": "succeeded"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "amount": amount_minor,
                "currency": currency.lower(),
                "description": description
            }
            resp = await client.post(f"{self.api_url}/charges", headers=self.headers, data=payload)
            resp.raise_for_status()
            return resp.json()
