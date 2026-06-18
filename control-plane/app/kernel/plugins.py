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

    async def verify_signature(self, raw_body: bytes, signature: str, secret_key: str) -> bool:
        """Verifies the webhook signature using the provider's specific scheme."""
        ...

    async def resolve_connection_identifier(self, headers: dict[str, str], payload: dict) -> Optional[str]:
        """Extracts the unique connection identifier (e.g. shop URL, webhook ID) from headers/payload."""
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
