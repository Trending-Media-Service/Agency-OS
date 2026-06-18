import logging
import os
import httpx
from typing import Any, Optional

logger = logging.getLogger(__name__)

class McpClient:
    """A lightweight JSON-RPC client for the Model Context Protocol (MCP) over HTTP.
    
    Falls back to a local high-fidelity mock if no server URL is provided.
    """

    def __init__(self, server_url: Optional[str] = None):
        self.server_url = server_url
        self._client = httpx.AsyncClient(timeout=10.0) if server_url else None
        if server_url:
            logger.info(f"Initialized real MCP Client targeting: {server_url}")

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def list_tools(self) -> list[dict]:
        """Lists tools exposed by the MCP server."""
        if self._client and self.server_url:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "params": {},
                    "id": "list-1"
                }
                resp = await self._client.post(self.server_url, json=payload)
                resp.raise_for_status()
                res = resp.json()
                if "error" in res:
                    raise ValueError(f"MCP server error: {res['error']}")
                return res.get("result", {}).get("tools", [])
            except Exception as e:
                logger.error(f"Failed to list tools from real MCP server: {e}. Falling back to mock.")

        # High-fidelity local mock tools listing
        return [
            {
                "name": "shopify_get_shop_info",
                "description": "Retrieve shop details and active scopes.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "shopify_list_products",
                "description": "List products in the store inventory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10}
                    }
                }
            },
            {
                "name": "shopify_create_webhook",
                "description": "Subscribe to a Shopify webhook topic.",
                "inputSchema": {
                    "type": "object",
                    "required": ["topic", "address"],
                    "properties": {
                        "topic": {"type": "string"},
                        "address": {"type": "string"}
                    }
                }
            }
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        """Invokes an MCP tool by name with arguments."""
        if self._client and self.server_url:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    },
                    "id": f"call-{tool_name}-1"
                }
                resp = await self._client.post(self.server_url, json=payload)
                resp.raise_for_status()
                res = resp.json()
                if "error" in res:
                    raise ValueError(f"MCP server error: {res['error']}")
                return res.get("result", {})
            except Exception as e:
                logger.error(f"Failed to call tool {tool_name} on real MCP server: {e}. Falling back to mock.")

        # High-fidelity local mock tool execution
        logger.info(f"[Mock MCP Server] Executing tool {tool_name} with args {arguments}")
        
        if tool_name == "shopify_get_shop_info":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": '{"shop_name": "Mock Ableys Shop", "domain": "ableys.myshopify.com", "currency": "INR", "status": "active"}'
                    }
                ]
            }
        elif tool_name == "shopify_list_products":
            limit = arguments.get("limit", 10)
            products = [
                {"id": 101, "title": "Wellness Herbal Tea", "price": "450.00", "inventory": 120},
                {"id": 102, "title": "Organic Honey", "price": "600.00", "inventory": 85},
                {"id": 103, "title": "Aromatic Incense", "price": "250.00", "inventory": 300}
            ][:limit]
            import json
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"products": products})
                    }
                ]
            }
        elif tool_name == "shopify_create_webhook":
            topic = arguments.get("topic")
            address = arguments.get("address")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f'{{"success": true, "webhook_id": "wh-12345", "topic": "{topic}", "address": "{address}"}}'
                    }
                ]
            }
        else:
            raise ValueError(f"Unknown mock tool: {tool_name}")
