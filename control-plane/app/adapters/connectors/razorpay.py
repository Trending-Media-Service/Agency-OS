import logging
import httpx
import base64
from typing import Any
from .base import register_connector

logger = logging.getLogger(__name__)

@register_connector
class RazorpayConnector:
    provider = "razorpay"

    def __init__(self, token: str, config: dict[str, Any]):
        self.token = token # Expecting key_id:key_secret format
        self.config = config
        self.api_url = config.get("api_url", "https://api.razorpay.com/v1")
        
        # Razorpay uses Basic Auth with Key ID and Key Secret
        encoded = base64.b64encode(token.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json"
        }

    async def verify_connection(self) -> bool:
        """Verifies Razorpay keys by fetching payments list."""
        if not self.token or self.token == "mock-razorpay-secret":
            logger.info("[Mock Razorpay] Verifying connection successfully")
            return True

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{self.api_url}/payments", headers=self.headers)
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"Razorpay connection verification failed: {e}")
                return False

    async def create_order(self, amount_minor: int, currency: str) -> dict:
        """Creates an order in Razorpay."""
        if not self.token or self.token == "mock-razorpay-secret":
            logger.info(f"[Mock Razorpay] Created order for {amount_minor} {currency}")
            return {"id": "order_mock_54321", "amount": amount_minor, "currency": currency, "status": "created"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "amount": amount_minor, # Razorpay expects amount in paise (minor unit)
                "currency": currency.upper(),
                "receipt": f"receipt_{amount_minor}"
            }
            resp = await client.post(f"{self.api_url}/orders", headers=self.headers, json=payload)
            resp.raise_for_status()
            return resp.json()
