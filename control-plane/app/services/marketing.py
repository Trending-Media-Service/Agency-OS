import logging
import json
import os

logger = logging.getLogger(__name__)

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
