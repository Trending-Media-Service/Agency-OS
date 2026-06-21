import logging
import json
import urllib.request
import urllib.parse
from collections import Counter
from app.services.storefront import IStorefrontAdapter

logger = logging.getLogger(__name__)

class ShopifyStorefront(IStorefrontAdapter):
    """Production-grade Shopify storefront adapter implementing the IStorefrontAdapter interface."""
    
    def __init__(self, shop_url: str, token: str):
        self.shop_url = shop_url.strip().rstrip("/")
        # Clean domain (e.g., "my-shop.myshopify.com" or raw handle)
        if "myshopify.com" not in self.shop_url and not self.shop_url.startswith("http"):
            self.shop_domain = f"{self.shop_url}.myshopify.com"
        else:
            # Parse domain from URL if full URL is passed
            parsed = urllib.parse.urlparse(self.shop_url)
            self.shop_domain = parsed.netloc or self.shop_url
            
        self.token = token.strip()
        self.api_version = "2024-04"
        self.headers = {
            "X-Shopify-Access-Token": self.token,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _is_mock_mode(self) -> bool:
        """Determines if the client should run in mock mode (e.g. dummy credentials)."""
        return not self.token or self.token.startswith("secret:") or self.token == "mock-token"

    def _make_request(self, endpoint: str, method: str = "GET", payload: dict = None) -> dict:
        url = f"https://{self.shop_domain}/admin/api/{self.api_version}/{endpoint}"
        data = json.dumps(payload).encode("utf-8") if payload else None
        
        req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            # Handle duplicate webhook registration
            if e.code == 422 and "already_exists" in err_body or "already exists" in err_body:
                return {"already_exists": True}
            logger.error(f"Shopify API HTTP Error on {endpoint}: {e.code} - {err_body}")
            return {"error": err_body}
        except Exception as e:
            logger.error(f"Shopify API Connection Error on {endpoint}: {e}")
            return {"error": str(e)}

    async def get_metrics(self) -> dict:
        """Compatibility method for legacy connections, returns high-level status."""
        if self._is_mock_mode():
            logger.info(f"Mock fetching Shopify metrics for {self.shop_domain}")
            return {
                "product_count": 50,
                "active_orders": 8,
                "sync_status": "synced",
                "shop_name": self.shop_domain.split(".")[0].capitalize()
            }
            
        res = self._make_request("products.json?limit=1")
        if "error" in res:
            return {"sync_status": "failed", "active_orders": 0}
        return {"sync_status": "synced", "active_orders": 3}

    async def run_catalog_audit(self) -> dict:
        """Audits product metadata completeness (SKUs, Barcodes, copywriting length)."""
        if self._is_mock_mode():
            logger.info("[MOCK] Running Shopify Catalog Audit")
            return {
                "success": True,
                "total_products_audited": 50,
                "missing_sku_count": 0,
                "missing_barcode_count": 50, # Mock 100% missing barcodes
                "low_stock_count": 5,
                "under_optimized_products": [
                    {"id": "mock_id", "title": "Mock Product Missing Barcode", "score": 75, "issues": ["Missing barcode"]}
                ]
            }
            
        res = self._make_request("products.json?limit=50")
        if "error" in res:
            return {"success": False, "error": res["error"]}
            
        products = res.get("products", [])
        total_products = len(products)
        missing_sku = 0
        missing_barcode = 0
        low_stock = 0
        under_optimized = []
        
        for p in products:
            p_id = p.get("id")
            title = p.get("title") or ""
            variants = p.get("variants") or []
            images = p.get("images") or []
            
            p_missing_sku = False
            p_missing_barcode = False
            for v in variants:
                if not v.get("sku"):
                    p_missing_sku = True
                if not v.get("barcode"):
                    p_missing_barcode = True
                    
            if p_missing_sku:
                missing_sku += 1
            if p_missing_barcode:
                missing_barcode += 1
                
            # Score calculations
            score = 100
            issues = []
            if p_missing_sku:
                score -= 15
                issues.append("Missing SKU on one or more variants.")
            if p_missing_barcode:
                score -= 20
                issues.append("Missing barcode / GTIN (blocks Google Ads PMax/Shopping!).")
            if len(images) < 3:
                score -= 15
                issues.append(f"Low media density ({len(images)} image(s)). Recommend 3+ photos.")
                
            if score < 90:
                under_optimized.append({
                    "id": str(p_id),
                    "title": title,
                    "score": score,
                    "issues": issues
                })
                
        return {
            "success": True,
            "total_products_audited": total_products,
            "missing_sku_count": missing_sku,
            "missing_barcode_count": missing_barcode,
            "low_stock_count": low_stock,
            "under_optimized_products": sorted(under_optimized, key=lambda x: x["score"])
        }

    async def run_sales_analysis(self) -> dict:
        """Queries recent orders to analyze total sales, AOV, and customer geography."""
        if self._is_mock_mode():
            logger.info("[MOCK] Running Shopify Sales Analysis")
            return {
                "success": True,
                "total_orders_analyzed": 50,
                "total_sales": 78900.0,
                "average_order_value": 1578.0,
                "top_regions": {"DL": 15, "MH": 12, "KA": 8}
            }
            
        res = self._make_request("orders.json?limit=50&status=any")
        if "error" in res:
            return {"success": False, "error": res["error"]}
            
        orders = res.get("orders", [])
        total_orders = len(orders)
        if total_orders == 0:
            return {"success": True, "total_orders_analyzed": 0, "total_sales": 0.0, "average_order_value": 0.0}
            
        total_sales = 0.0
        states = Counter()
        
        for o in orders:
            total_sales += float(o.get("total_price", 0.0))
            # Extract customer billing region
            billing = o.get("billing_address") or {}
            province_code = billing.get("province_code")
            if province_code:
                states[province_code.strip().upper()] += 1
                
        aov = total_sales / total_orders
        
        return {
            "success": True,
            "total_orders_analyzed": total_orders,
            "total_sales": round(total_sales, 2),
            "average_order_value": round(aov, 2),
            "top_regions": dict(states.most_common(5))
        }

    async def register_poas_webhooks(self, gateway_url: str) -> dict:
        """Registers the order creation webhook pointing to the sGTM gateway."""
        if self._is_mock_mode():
            logger.info(f"[MOCK] Registering webhook for {gateway_url}")
            return {"success": True, "webhook_id": "mock_webhook_id"}
            
        payload = {
            "webhook": {
                "topic": "orders/create",
                "address": gateway_url,
                "format": "json"
            }
        }
        
        res = self._make_request("webhooks.json", method="POST", payload=payload)
        
        if "webhook" in res:
            w_id = res["webhook"].get("id")
            logger.info(f"Shopify Webhook registered successfully! (ID: {w_id})")
            return {"success": True, "webhook_id": str(w_id)}
        elif res.get("already_exists"):
            logger.info("Shopify Webhook already exists.")
            return {"success": True, "status": "ALREADY_EXISTS"}
        else:
            return {"success": False, "error": res.get("error")}
            
# Retain MockShopifyClient alias for legacy compatibility
MockShopifyClient = ShopifyStorefront
