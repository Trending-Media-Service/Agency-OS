"""L6 Tool Registry (§7) for binding LLM agent functions to governed Op proposals."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from app.kernel.optypes import OpSpec, Severity, Reversibility

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}

    def register_tool(self, name: str, schema: dict[str, Any], handler: Callable[..., list[OpSpec]]) -> None:
        self._tools[name] = {
            "schema": schema,
            "handler": handler
        }
        logger.info(f"Registered LLM tool: {name}")

    def get_tool(self, name: str) -> Optional[dict[str, Any]]:
        return self._tools.get(name)

    def get_schemas(self) -> list[dict[str, Any]]:
        return [t["schema"] for t in self._tools.values()]


registry = ToolRegistry()


# ---------------------------------------------------------------- standard tools

def _grow_bid_adjust_handler(tenant_id: str, brand_id: str, campaign_id: str, new_bid_minor: int) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.bid.adjust",
            params={
                "campaign_id": campaign_id,
                "new_bid_minor": new_bid_minor
            },
            severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE)
        )
    ]


def _grow_budget_reallocate_handler(tenant_id: str, brand_id: str, source_campaign_id: str,
                                    target_campaign_id: str, amount_minor: int) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.budget.reallocate",
            params={
                "source_campaign_id": source_campaign_id,
                "target_campaign_id": target_campaign_id,
                "transfer_amount_minor": amount_minor
            },
            severity=Severity(impact=3, reversibility=Reversibility.COMPENSATABLE)
        )
    ]


def _grow_campaign_pause_handler(tenant_id: str, brand_id: str, campaign_id: str) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.campaign.pause",
            params={
                "campaign_id": campaign_id
            },
            severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE)
        )
    ]


registry.register_tool(
    name="grow_bid_adjust",
    schema={
        "name": "grow_bid_adjust",
        "description": "Adjust the bidding price for an active ad campaign.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "campaign_id": {"type": "STRING"},
                "new_bid_minor": {"type": "INTEGER"}
            },
            "required": ["brand_id", "campaign_id", "new_bid_minor"]
        }
    },
    handler=_grow_bid_adjust_handler
)

registry.register_tool(
    name="grow_budget_reallocate",
    schema={
        "name": "grow_budget_reallocate",
        "description": "Reallocate advertising budget from one campaign to another.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "source_campaign_id": {"type": "STRING"},
                "target_campaign_id": {"type": "STRING"},
                "amount_minor": {"type": "INTEGER"}
            },
            "required": ["brand_id", "source_campaign_id", "target_campaign_id", "amount_minor"]
        }
    },
    handler=_grow_budget_reallocate_handler
)

registry.register_tool(
    name="grow_campaign_pause",
    schema={
        "name": "grow_campaign_pause",
        "description": "Pause an active ad campaign.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "campaign_id": {"type": "STRING"}
            },
            "required": ["brand_id", "campaign_id"]
        }
    },
    handler=_grow_campaign_pause_handler
)


def parse_chat_to_tool_call(text: str) -> Optional[tuple[str, dict]]:
    """Simulates/parses text to extract tool call name and arguments (regex-backed fallback)."""
    normalized = text.lower()
    
    # 1. grow_bid_adjust (e.g. "adjust bid for campaign camp-123 to 50 inr")
    match_bid_val = re.search(r'([0-9]+)\s*inr', normalized)
    match_camp = re.search(r'campaign\s*([a-zA-Z0-9_-]+)', normalized)
    if "bid" in normalized and match_bid_val and match_camp:
        try:
            val = int(match_bid_val.group(1)) * 100
            camp_id = match_camp.group(1)
            # Find brand_id if present, fallback to default
            match_brand = re.search(r'brand\s*([a-zA-Z0-9_-]+)', normalized)
            brand_id = match_brand.group(1) if match_brand else "brand-grow-test"
            return "grow_bid_adjust", {"brand_id": brand_id, "campaign_id": camp_id, "new_bid_minor": val}
        except ValueError:
            pass

    # 2. grow_campaign_pause (e.g. "pause campaign camp-456")
    match_pause = re.search(r'pause\s*campaign\s*([a-zA-Z0-9_-]+)', normalized)
    if match_pause:
        camp_id = match_pause.group(1)
        match_brand = re.search(r'brand\s*([a-zA-Z0-9_-]+)', normalized)
        brand_id = match_brand.group(1) if match_brand else "brand-grow-test"
        return "grow_campaign_pause", {"brand_id": brand_id, "campaign_id": camp_id}

    return None

