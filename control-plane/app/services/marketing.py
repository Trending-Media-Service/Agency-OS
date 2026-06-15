import logging

logger = logging.getLogger(__name__)

class MockMarketingClient:
    # In-memory storage for campaigns
    _campaigns = {}

    @classmethod
    def clear(cls):
        cls._campaigns.clear()

    def __init__(self, provider: str = "google-ads"):
        self.provider = provider

    async def create_campaign(self, campaign_id: str, name: str, budget_minor: int, bid_minor: int) -> bool:
        self._campaigns[campaign_id] = {
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
        logger.info(f"Mock created campaign {campaign_id} ({name}) via {self.provider} with budget {budget_minor/100:.2f}")
        return True

    async def update_campaign(self, campaign_id: str, budget_minor: int = None, bid_minor: int = None, status: str = None) -> bool:
        if campaign_id not in self._campaigns:
            logger.error(f"Campaign {campaign_id} not found")
            return False
        if budget_minor is not None:
            self._campaigns[campaign_id]["budget_minor"] = budget_minor
        if bid_minor is not None:
            self._campaigns[campaign_id]["bid_minor"] = bid_minor
        if status is not None:
            self._campaigns[campaign_id]["status"] = status
        logger.info(f"Mock updated campaign {campaign_id}: budget={budget_minor}, bid={bid_minor}, status={status}")
        return True

    async def delete_campaign(self, campaign_id: str) -> bool:
        if campaign_id in self._campaigns:
            del self._campaigns[campaign_id]
            logger.info(f"Mock deleted campaign {campaign_id}")
            return True
        return False

    async def get_campaign(self, campaign_id: str) -> dict | None:
        return self._campaigns.get(campaign_id)

    async def get_performance(self, campaign_id: str) -> dict | None:
        camp = self._campaigns.get(campaign_id)
        if not camp:
            return None
            
        budget = camp["budget_minor"]
        # Mock ROI: low ROI if "fail" in name
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
