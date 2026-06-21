from abc import ABC, abstractmethod

class IStorefrontAdapter(ABC):
    """Unified interface for all storefront channels (Shopify, WooCommerce, etc.) in Agency OS."""
    
    @abstractmethod
    async def run_catalog_audit(self) -> dict:
        """Audits the product catalog for SKU completeness, barcodes (GTINs), and metadata quality."""
        pass

    @abstractmethod
    async def run_sales_analysis(self) -> dict:
        """Analyzes recent orders to calculate AOV, total sales, and customer geographic hubs."""
        pass

    @abstractmethod
    async def register_poas_webhooks(self, gateway_url: str) -> dict:
        """Registers purchase/fulfillment webhooks pointing to the sGTM tracking gateway."""
        pass
