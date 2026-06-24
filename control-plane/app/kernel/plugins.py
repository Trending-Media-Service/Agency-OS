"""L3 Plugin Registry (§5) for third-party webhook integrations."""
from __future__ import annotations

import hmac
import hashlib
import logging
from typing import Any, Optional, Protocol

from app.kernel.optypes import OpSpec, Severity, Reversibility

logger = logging.getLogger(__name__)


class Plugin(Protocol):
    provider: str  # e.g., "shopify"

    async def extract_signature(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        """Extracts the webhook signature/token from headers or payload."""
        ...

    async def verify_signature(self, raw_body: bytes, signature: str, secret_key: str) -> bool:
        """Verifies the webhook signature using the provider's specific scheme."""
        ...

    async def resolve_connection_identifier(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        """Extracts the unique connection identifier (e.g. shop URL, webhook ID) from headers/payload."""
        ...

    async def extract_event_type(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        """Extracts the webhook event type from headers or payload."""
        ...

    async def translate_webhook(self, event_type: str, payload: dict, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Translates the validated webhook payload into a list of proposed OpSpecs."""
        ...


_REGISTRY: dict[str, Plugin] = {}


def register_plugin(plugin: Plugin) -> None:
    _REGISTRY[plugin.provider] = plugin
    logger.info(f"Registered plugin for provider: {plugin.provider}")


def get_plugin(provider: str) -> Optional[Plugin]:
    return _REGISTRY.get(provider)


class ShopifyPlugin:
    provider = "shopify"

    async def extract_signature(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        # Normalize header keys to lowercase
        normalized = {k.lower(): v for k, v in headers.items()}
        return normalized.get("x-shopify-hmac-sha256")

    async def verify_signature(self, raw_body: bytes, signature: str, secret_key: str) -> bool:
        """Shopify webhook signature is HMAC-SHA256 of raw body using webhook secret."""
        if not secret_key:
            logger.warning("Shopify secret key missing; bypassing verification (unsafe)")
            return True
        expected = hmac.new(
            secret_key.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).digest()
        import base64
        expected_b64 = base64.b64encode(expected).decode("utf-8")
        return hmac.compare_digest(expected_b64, signature)

    async def resolve_connection_identifier(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        """Shopify sends the shop's domain in X-Shopify-Shop-Domain header."""
        # Normalize header keys to lowercase
        normalized = {k.lower(): v for k, v in headers.items()}
        return normalized.get("x-shopify-shop-domain")

    async def extract_event_type(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        # Normalize header keys to lowercase
        normalized = {k.lower(): v for k, v in headers.items()}
        return normalized.get("x-shopify-topic")

    async def translate_webhook(self, event_type: str, payload: dict, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Translates Shopify webhooks (e.g. orders/create) into proposed Ops."""
        if event_type == "orders/create":
            order_id = str(payload.get("id"))
            
            # Call Shopify MCP server to retrieve verified order details
            from app.services.mcp import McpClient
            import json
            
            mcp = McpClient()
            try:
                mcp_res = await mcp.call_tool("shopify_get_order", {"order_id": order_id})
                content_text = mcp_res.get("content", [{}])[0].get("text", "{}")
                order_data = json.loads(content_text)
            except Exception as e:
                logger.error(f"Failed to fetch order {order_id} via Shopify MCP server: {e}")
                # Fallback to webhook payload if MCP call fails to ensure resilience
                order_data = payload

            total_price = order_data.get("total_price", "0.00")
            try:
                amount_minor = int(float(total_price) * 100)
            except (ValueError, TypeError):
                amount_minor = 0

            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="manage",
                    action="manage.shopify.sync_order",
                    params={
                        "order_id": order_id,
                        "amount_minor": amount_minor,
                        "placed_at": order_data.get("created_at"),
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                )
            ]
        return []


def normalize_petpooja_order(order_data: dict) -> dict:
    """Normalizes Petpooja order data (from webhook or pull API) into a unified format."""
    order_part = order_data.get("Order", {})
    order_id = str(order_part.get("orderID") or "")
    
    # Extract total amount
    total_val = order_part.get("total")
    try:
        total_amount = float(total_val) if total_val is not None else 0.0
    except (ValueError, TypeError):
        total_amount = 0.0
        
    placed_at_str = order_part.get("created_on") or order_part.get("order_date")
    
    normalized_items = []
    items_part = order_data.get("OrderItem", [])
    for item in items_part:
        # Handle unit price
        price_val = item.get("price")
        try:
            price = float(price_val) if price_val is not None else 0.0
        except (ValueError, TypeError):
            price = 0.0
            
        # Handle quantity
        qty_val = item.get("quantity")
        try:
            qty = int(float(qty_val)) if qty_val is not None else 1
        except (ValueError, TypeError):
            qty = 1
            
        # Handle discount (could be "discount" or "total_discount")
        discount_val = item.get("discount") if "discount" in item else item.get("total_discount")
        try:
            discount = float(discount_val) if discount_val is not None else 0.0
        except (ValueError, TypeError):
            discount = 0.0
            
        normalized_items.append({
            "price": price,
            "quantity": qty,
            "discount": discount,
            "name": item.get("name", "")
        })
        
    return {
        "order_id": order_id,
        "total_amount": total_amount,
        "placed_at": placed_at_str,
        "items": normalized_items
    }


class PetpoojaPlugin:
    provider = "petpooja"

    async def extract_signature(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        # Petpooja sends token in the body (case-insensitive key "token" or "Token")
        return payload.get("token") or payload.get("Token")

    async def verify_signature(self, raw_body: bytes, signature: str, secret_key: str) -> bool:
        # If no secret key is configured in the database connection, bypass verification
        if not secret_key:
            return True
        if not signature:
            return False
        return hmac.compare_digest(signature, secret_key)

    async def resolve_connection_identifier(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        # Extract restID from properties.Restaurant.restID (Webhook push)
        # or from Restaurant.restID (Pull API order object if processed individually)
        properties = payload.get("properties", {})
        rest_id = properties.get("Restaurant", {}).get("restID")
        if not rest_id:
            rest_id = payload.get("Restaurant", {}).get("restID")
        return rest_id

    async def extract_event_type(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        # Petpooja webhook uses the "event" field in the body
        return payload.get("event")

    async def translate_webhook(self, event_type: str, payload: dict, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Translates Petpooja webhook (e.g. event="orderdetails") into proposed Ops."""
        if event_type == "orderdetails":
            order_data = payload.get("properties", {})
            normalized = normalize_petpooja_order(order_data)
            if not normalized["order_id"]:
                logger.error("Petpooja webhook missing orderID")
                return []
                
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="manage",
                    action="manage.petpooja.sync_order",
                    params=normalized,
                    severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                )
            ]
        return []
