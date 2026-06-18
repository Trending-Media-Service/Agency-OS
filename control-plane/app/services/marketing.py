import logging
import json
import os
from typing import Protocol, Any, Optional

logger = logging.getLogger(__name__)

class MarketingClient(Protocol):
    """Universal interface for marketing channel integrations (§5)."""
    provider: str

    async def create_campaign(self, campaign_id: str, name: str, budget_minor: int, bid_minor: int) -> bool:
        ...

    async def update_campaign(
        self, 
        campaign_id: str, 
        budget_minor: Optional[int] = None, 
        bid_minor: Optional[int] = None, 
        status: Optional[str] = None
    ) -> bool:
        ...

    async def delete_campaign(self, campaign_id: str) -> bool:
        ...

    async def get_campaign(self, campaign_id: str) -> Optional[dict]:
        ...

    async def get_performance(self, campaign_id: str) -> Optional[dict]:
        ...


def get_marketing_client(provider: str, token: Optional[str] = None, config: Optional[dict] = None) -> MarketingClient:
    """Factory to resolve the active marketing client for a provider."""
    # 1. Check for test environment or explicit mock provider
    env = os.getenv("AOS_ENV", "development")
    if env == "test" or provider == "mock":
        return MockMarketingClient(provider=provider)

    # 2. If no credentials (token) are provided for real channels, raise ValueError
    if provider in ("google-ads", "meta-ads"):
        if not token:
            raise ValueError(f"Credentials (token) are required for provider: {provider}")
        
        if provider == "google-ads":
            from app.services.google_ads import GoogleAdsClient
            return GoogleAdsClient(token=token, config=config)
            
        # Meta Ads is not implemented yet in this step (P3-1).
        # Raise NotImplementedError until P3-2.
        raise NotImplementedError(f"Real integration for provider {provider} is not implemented in this phase")

    # 3. For any unknown providers, raise ValueError
    raise ValueError(f"Unsupported marketing provider: {provider}")


class MockMarketingClient:
    # Persistent storage file in the workspace scratch directory
    _file_path = os.path.join(os.path.dirname(__file__), "../../scratch/mock_marketing_campaigns.json")

    @classmethod
    def _load(cls) -> dict:
        if os.path.exists(cls._file_path):
            try:
                with open(cls._file_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load mock campaigns: {e}")
                return {}
        return {}

    @classmethod
    def _save(cls, data: dict):
        os.makedirs(os.path.dirname(cls._file_path), exist_ok=True)
        try:
            with open(cls._file_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save mock campaigns: {e}")

    @classmethod
    def clear(cls):
        if os.path.exists(cls._file_path):
            try:
                os.remove(cls._file_path)
            except Exception:
                pass

    def __init__(self, provider: str = "google-ads"):
        self.provider = provider

    async def create_campaign(self, campaign_id: str, name: str, budget_minor: int, bid_minor: int) -> bool:
        campaigns = self._load()
        campaigns[campaign_id] = {
            "id": campaign_id,
            "name": name,
            "budget_minor": budget_minor,
            "bid_minor": bid_minor,
            "status": "ACTIVE",
            "impressions": 0,
            "clicks": 0,
            "spend_minor": 0,
            "conversions": 0
        }
        self._save(campaigns)
        logger.info(f"Mock created campaign {campaign_id} ({name}) via {self.provider} with budget {budget_minor/100:.2f}")
        return True

    async def update_campaign(self, campaign_id: str, budget_minor: int = None, bid_minor: int = None, status: str = None) -> bool:
        campaigns = self._load()
        if campaign_id not in campaigns:
            logger.error(f"Campaign {campaign_id} not found")
            return False
        if budget_minor is not None:
            campaigns[campaign_id]["budget_minor"] = budget_minor
        if bid_minor is not None:
            campaigns[campaign_id]["bid_minor"] = bid_minor
        if status is not None:
            campaigns[campaign_id]["status"] = status
        self._save(campaigns)
        logger.info(f"Mock updated campaign {campaign_id}: budget={budget_minor}, bid={bid_minor}, status={status}")
        return True

    async def delete_campaign(self, campaign_id: str) -> bool:
        campaigns = self._load()
        if campaign_id in campaigns:
            del campaigns[campaign_id]
            self._save(campaigns)
            logger.info(f"Mock deleted campaign {campaign_id}")
            return True
        return False

    async def get_campaign(self, campaign_id: str) -> dict | None:
        campaigns = self._load()
        return campaigns.get(campaign_id)

    async def get_performance(self, campaign_id: str) -> dict | None:
        campaigns = self._load()
        camp = campaigns.get(campaign_id)
        if not camp:
            return None
            
        budget = camp["budget_minor"]
        roi = 1.5
        if "fail" in camp["name"].lower():
            roi = 0.5
            
        spend = int(budget * 0.8)
        revenue = int(spend * roi)
        conversions = int(spend / 1000)
        
        return {
            "campaign_id": campaign_id,
            "impressions": spend * 10,
            "clicks": spend // 2,
            "spend_minor": spend,
            "revenue_minor": revenue,
            "conversions": conversions,
            "roi": roi
        }
