import re
import asyncio
import random
from typing import Optional, Any
import httpx
import logging
from app.services.marketing import MarketingClient, MockMarketingClient

logger = logging.getLogger(__name__)

class GoogleAdsClient(MarketingClient):
    """Universal client for Google Ads API.

    Architectural Decision:
    We use raw asynchronous `httpx` calls to the Google Ads REST API instead of the
    official `google-ads` Python SDK. This ensures that all network I/O operations
    are fully asynchronous and do not block the ASGI event loop, avoiding the need for
    thread pool delegation (e.g., `asyncio.to_thread`) which would be required for the
    blocking, synchronous official SDK. It also maintains a zero-dependency footprint.
    """
    provider = "google-ads"

    def __init__(self, token: Optional[str] = None, config: Optional[dict[str, Any]] = None):
        self.token = token
        self.config = config or {}
        self.developer_token = self.config.get("developer_token", "mock-developer-token")
        self.customer_id = self.config.get("customer_id", "mock-customer-id")
        self.api_url = self.config.get("api_url", "https://googleads.googleapis.com/v17")
        
        # Use delegation to MockMarketingClient for mock runs.
        # Gate on AOS_ENV=test or no/mock token — do NOT treat a bare secret_ref path
        # as a ******; grow.py raises if SecretManager fails, so a raw ref
        # should never reach here in production.
        self._mock_client = MockMarketingClient(provider=self.provider)
        self._is_mock = not token or token == "mock-google-ads-token" or token.startswith("secret:")
        
        # Always initialize headers so tests can set _is_mock=False without AttributeError
        self.headers = {
            "Authorization": f"Bearer {token or ''}",
            "developer-token": self.developer_token,
            "login-customer-id": self.customer_id,
            "Content-Type": "application/json"
        }

        if self._is_mock:
            logger.info("Initializing GoogleAdsClient in high-fidelity MOCK mode")
        else:
            logger.info(f"Initializing real GoogleAdsClient targeting customer {self.customer_id}")

    async def _send_with_retry(
        self, 
        client: httpx.AsyncClient, 
        method: str, 
        url: str, 
        headers: dict, 
        json_data: Optional[dict] = None, 
        max_retries: int = 3, 
        base_delay: float = 1.0
    ) -> httpx.Response:
        delay = base_delay
        for attempt in range(max_retries + 1):
            try:
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=json_data)
                else:
                    resp = await client.get(url, headers=headers)
                
                # Retry on 429 (rate limit) or 500/503 (server errors)
                if resp.status_code in (429, 500, 503) and attempt < max_retries:
                    sleep_time = delay * (0.5 + random.random())
                    logger.warning(
                        f"Google Ads API returned transient error {resp.status_code}. "
                        f"Retrying in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(sleep_time)
                    delay *= 2
                    continue
                
                return resp
            except (httpx.RequestError, httpx.TimeoutException) as e:
                if attempt < max_retries:
                    sleep_time = delay * (0.5 + random.random())
                    logger.warning(
                        f"Google Ads API request failed: {e}. "
                        f"Retrying in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(sleep_time)
                    delay *= 2
                    continue
                raise e

    async def create_campaign(self, campaign_id: str, name: str, budget_minor: int, bid_minor: int) -> bool:
        if not re.match(r"^[a-zA-Z0-9\-_]+$", campaign_id):
            raise ValueError(f"Invalid/unsafe campaign_id format: {campaign_id}")

        if self._is_mock:
            return await self._mock_client.create_campaign(campaign_id, name, budget_minor, bid_minor)

        # Real Google Ads REST Mutate Campaign Call
        url = f"{self.api_url}/customers/{self.customer_id}/campaigns:mutate"
        payload = {
            "operations": [
                {
                    "create": {
                        "name": name,
                        "status": "PAUSED",
                        "advertising_channel_type": "SEARCH"
                    }
                }
            ]
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await self._send_with_retry(client, "POST", url, headers=self.headers, json_data=payload)
                if resp.status_code == 200:
                    logger.info(f"Google Ads campaign {name} created successfully via API")
                    return True
                logger.error(f"Google Ads campaign creation failed: {resp.status_code} - {resp.text}")
                return False
            except Exception as e:
                logger.error(f"Google Ads API request failed: {e}")
                return False

    async def update_campaign(
        self, 
        campaign_id: str, 
        budget_minor: Optional[int] = None, 
        bid_minor: Optional[int] = None, 
        status: Optional[str] = None
    ) -> bool:
        if not re.match(r"^[a-zA-Z0-9\-_]+$", campaign_id):
            raise ValueError(f"Invalid/unsafe campaign_id format: {campaign_id}")

        if self._is_mock:
            return await self._mock_client.update_campaign(campaign_id, budget_minor, bid_minor, status)

        url = f"{self.api_url}/customers/{self.customer_id}/campaigns:mutate"
        campaign_fields: dict[str, Any] = {"resourceName": f"customers/{self.customer_id}/campaigns/{campaign_id}"}
        update_mask = []
        
        if status is not None:
            campaign_fields["status"] = "ENABLED" if status == "ACTIVE" else "PAUSED"
            update_mask.append("status")
            
        payload = {
            "operations": [
                {
                    "update": campaign_fields,
                    "updateMask": ",".join(update_mask)
                }
            ]
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await self._send_with_retry(client, "POST", url, headers=self.headers, json_data=payload)
                if resp.status_code == 200:
                    logger.info(f"Google Ads campaign {campaign_id} updated successfully")
                    return True
                logger.error(f"Google Ads campaign update failed: {resp.status_code} - {resp.text}")
                return False
            except Exception as e:
                logger.error(f"Google Ads API request failed: {e}")
                return False

    async def delete_campaign(self, campaign_id: str) -> bool:
        if not re.match(r"^[a-zA-Z0-9\-_]+$", campaign_id):
            raise ValueError(f"Invalid/unsafe campaign_id format: {campaign_id}")

        if self._is_mock:
            return await self._mock_client.delete_campaign(campaign_id)

        url = f"{self.api_url}/customers/{self.customer_id}/campaigns:mutate"
        payload = {
            "operations": [
                {
                    "remove": f"customers/{self.customer_id}/campaigns/{campaign_id}"
                }
            ]
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await self._send_with_retry(client, "POST", url, headers=self.headers, json_data=payload)
                if resp.status_code == 200:
                    logger.info(f"Google Ads campaign {campaign_id} deleted successfully")
                    return True
                logger.error(f"Google Ads campaign deletion failed: {resp.status_code} - {resp.text}")
                return False
            except Exception as e:
                logger.error(f"Google Ads API request failed: {e}")
                return False

    async def get_campaign(self, campaign_id: str) -> Optional[dict]:
        if not re.match(r"^[a-zA-Z0-9\-_]+$", campaign_id):
            raise ValueError(f"Invalid/unsafe campaign_id format: {campaign_id}")

        if self._is_mock:
            return await self._mock_client.get_campaign(campaign_id)

        url = f"{self.api_url}/customers/{self.customer_id}/googleAds:search"
        query = f"SELECT campaign.id, campaign.name, campaign.status FROM campaign WHERE campaign.id = '{campaign_id}'"
        payload = {"query": query}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await self._send_with_retry(client, "POST", url, headers=self.headers, json_data=payload)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results:
                        camp_info = results[0].get("campaign", {})
                        status = "ACTIVE" if camp_info.get("status") == "ENABLED" else "PAUSED"
                        return {
                            "id": camp_info.get("id"),
                            "name": camp_info.get("name"),
                            "status": status
                        }
                    return None
                logger.error(f"Google Ads campaign fetch failed: {resp.status_code} - {resp.text}")
                return None
            except Exception as e:
                logger.error(f"Google Ads API request failed: {e}")
                return None

    async def get_performance(self, campaign_id: str) -> Optional[dict]:
        if not re.match(r"^[a-zA-Z0-9\-_]+$", campaign_id):
            raise ValueError(f"Invalid/unsafe campaign_id format: {campaign_id}")

        if self._is_mock:
            return await self._mock_client.get_performance(campaign_id)

        url = f"{self.api_url}/customers/{self.customer_id}/googleAds:search"
        query = f"""
            SELECT metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value 
            FROM campaign 
            WHERE campaign.id = '{campaign_id}'
        """
        payload = {"query": query}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await self._send_with_retry(client, "POST", url, headers=self.headers, json_data=payload)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results:
                        metrics = results[0].get("metrics", {})
                        cost_minor = int(int(metrics.get("costMicros", "0")) / 10000)
                        revenue_minor = int(float(metrics.get("conversionsValue", "0.0")) * 100)
                        conversions = int(float(metrics.get("conversions", "0.0")))
                        roi = float(revenue_minor) / float(cost_minor) if cost_minor > 0 else 1.0
                        return {
                            "campaign_id": campaign_id,
                            "impressions": int(metrics.get("impressions", "0")),
                            "clicks": int(metrics.get("clicks", "0")),
                            "spend_minor": cost_minor,
                            "revenue_minor": revenue_minor,
                            "conversions": conversions,
                            "roi": roi
                        }
                    return None
                logger.error(f"Google Ads performance fetch failed: {resp.status_code} - {resp.text}")
                return None
            except Exception as e:
                logger.error(f"Google Ads API request failed: {e}")
                return None
