import logging

logger = logging.getLogger(__name__)

class MockShopifyClient:
    def __init__(self, shop_url: str, token: str):
        self.shop_url = shop_url
        self.token = token

    async def get_metrics(self) -> dict:
        """Simulates fetching metrics from Shopify Admin API."""
        logger.info(f"Mock fetching Shopify metrics for {self.shop_url}")
        
        brand = self.shop_url.split(".")[0]
        
        metrics = {
            "product_count": 42,
            "active_orders": 5,
            "sync_status": "synced",
            "shop_name": brand.capitalize()
        }
        
        if "fail" in brand:
             metrics["sync_status"] = "failed"
             metrics["active_orders"] = 0
             
        return metrics
