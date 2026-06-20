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
        "title": "Adjust Campaign Bid",
        "domain": "grow",
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
        "title": "Reallocate Campaign Budget",
        "domain": "grow",
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
        "title": "Pause Ad Campaign",
        "domain": "grow",
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


def _grow_value_engine_optimize_handler(
    tenant_id: str,
    brand_id: str,
    campaign_id: str,
    posture: str,
    macro_value_minor: int,
    micro_conversions: list[dict[str, Any]]
) -> list[OpSpec]:
    # Calculate optimized value V_opt using the macro-micro mapping formula:
    # V_opt = V_macro + sum( v_micro_i * (1 - d_i) )
    micro_contribution = 0.0
    for step in micro_conversions:
        val = step.get("value_minor", 0)
        dropoff = step.get("dropoff_rate", 0.0)
        micro_contribution += val * (1.0 - dropoff)
        
    v_opt_minor = int(macro_value_minor + micro_contribution)
    
    # Posture-based target ROAS adjustment
    # Conservative: 110% baseline (protect margins), Aggressive: 85% baseline (maximize scale)
    roas_multiplier = 1.0
    if posture.lower() == "conservative":
        roas_multiplier = 1.10
    elif posture.lower() == "aggressive":
        roas_multiplier = 0.85
        
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.value_bidding.optimize",
            params={
                "campaign_id": campaign_id,
                "posture": posture,
                "macro_value_minor": macro_value_minor,
                "v_opt_minor": v_opt_minor,
                "roas_multiplier": roas_multiplier,
                "micro_conversions_audited": len(micro_conversions)
            },
            severity=Severity(impact=3, reversibility=Reversibility.COMPENSATABLE)
        )
    ]


def _presence_consent_mode_audit_handler(tenant_id: str, brand_id: str, url: str) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="presence",
            action="presence.consent_mode.audit",
            params={
                "url": url,
                "audit_mode": "consent-v2-verification",
                "required_regions": ["EEA", "UK"]
            },
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        )
    ]


def _grow_meridian_mmm_audit_handler(tenant_id: str, brand_id: str, lookback_days: int = 90) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.meridian_mmm.audit",
            params={
                "lookback_days": lookback_days,
                "channels": ["search", "pmax", "meta-ads", "organic"],
                "report_format": "cfo-ready-pdf"
            },
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        )
    ]


def _manage_merchant_feed_shield_handler(tenant_id: str, brand_id: str, merchant_id: int) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="manage",
            action="manage.merchant_center.scan",
            params={
                "merchant_id": merchant_id,
                "shield_active": True,
                "scan_types": ["policy_violations", "item_disapprovals"]
            },
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        )
    ]


def _grow_programmatic_dv360_connect_handler(tenant_id: str, brand_id: str, advertiser_id: str, secret_ref: str) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.dv360.connect",
            params={
                "advertiser_id": advertiser_id,
                "secret_ref": secret_ref,
                "sync_audiences": ["high_intent_search", "custom_segments"]
            },
            severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
        )
    ]


def _grow_ai_readiness_audit_handler(tenant_id: str, brand_id: str, campaign_id: str) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.ai_readiness.audit",
            params={
                "campaign_id": campaign_id,
                "checks": ["match_type_cleanup", "duplicate_keywords", "budget_caps"],
                "target_engine": "broad_match_pmax"
            },
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        )
    ]


def _grow_youtube_creator_connect_handler(tenant_id: str, brand_id: str, channel_id: str) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            action="grow.youtube_creator.connect",
            params={
                "channel_id": channel_id,
                "amplification_mode": "shorts_ctv_bidding",
                "sync_creator_analytics": True
            },
            severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
        )
    ]


# ---------------------------------------------------------------- structured operator-action tools
# These back the console's explicit Action Panel (no free-text parsing). Each handler
# builds the same OpSpec an adapter.plan() would, from structured params.

def _provision_web_host_handler(tenant_id: str, brand_id: str, domain: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="provision",
        action="provision.web_host.create",
        params={"domain": domain, "recipe": "web-host", "version": "0.1.0"},
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
    )]


def _build_deliver_handler(tenant_id: str, brand_id: str, intent: str, repo: Optional[str] = None) -> list[OpSpec]:
    import uuid
    from app.kernel.optypes import Severity, Reversibility, Money
    return [OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="build",
        action="build.deliver",
        params={
            "intent": intent,
            "branch_name": f"aos-build-{uuid.uuid4().hex[:8]}",
            "repo": repo or "git@github.com:ableys/brand-site.git"
        },
        severity=Severity(impact=2, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(amount_minor=1000, currency="INR"),
    )]


def _manage_shopify_connect_handler(tenant_id: str, brand_id: str, shop_url: str, credential: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": credential, "config": {"shop_url": shop_url}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )]


def _manage_diagnostics_handler(tenant_id: str, brand_id: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="manage",
        action="manage.diagnostics.check",
        params={"log_source": "cloud-run-logs"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
    )]


def _presence_citation_audit_handler(tenant_id: str, brand_id: str, competitors: str = "") -> list[OpSpec]:
    comp_list = [c.strip() for c in competitors.replace(",", " ").split() if c.strip()]
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="presence",
        action="presence.citation.audit",
        params={"brand_id": brand_id, "competitors": comp_list},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
    )]


registry.register_tool(
    name="provision_web_host",
    schema={
        "name": "provision_web_host",
        "title": "Provision Web Host",
        "description": "Provision a Cloud Run web host for a domain.",
        "domain": "provision",
        "parameters": {
            "type": "OBJECT",
            "properties": {"domain": {"type": "STRING", "description": "Domain to host, e.g. ableys.in"}},
            "required": ["domain"],
        },
    },
    handler=_provision_web_host_handler,
)

registry.register_tool(
    name="manage_shopify_connect",
    schema={
        "name": "manage_shopify_connect",
        "title": "Connect Shopify Store",
        "description": "Connect a Shopify store (creates a governed Connection).",
        "domain": "manage",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "shop_url": {"type": "STRING", "description": "myshop.myshopify.com"},
                "credential": {"type": "STRING", "description": "Secret Manager reference for the API token"},
            },
            "required": ["shop_url", "credential"],
        },
    },
    handler=_manage_shopify_connect_handler,
)

registry.register_tool(
    name="manage_diagnostics",
    schema={
        "name": "manage_diagnostics",
        "title": "Run Diagnostics",
        "description": "Run diagnostics on the brand's Cloud Run logs.",
        "domain": "manage",
        "parameters": {"type": "OBJECT", "properties": {}, "required": []},
    },
    handler=_manage_diagnostics_handler,
)


def _connection_rotate_secret_handler(
    tenant_id: str,
    brand_id: str,
    provider: str,
    credential: str,
    config: dict = None,
    old_credential: str = None,
    old_config: dict = None
) -> list[OpSpec]:
    return [
        OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="manage",
            action="manage.connection.rotate",
            params={
                "provider": provider,
                "credential": credential,
                "config": config or {},
                "old_credential": old_credential,
                "old_config": old_config or {},
            },
            severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
        )
    ]


registry.register_tool(
    name="connection_rotate_secret",
    schema={
        "name": "connection_rotate_secret",
        "title": "Rotate Connection Secret",
        "description": "Rotate the credentials and configuration of an existing Connection.",
        "domain": "manage",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "provider": {"type": "STRING"},
                "credential": {"type": "STRING", "description": "New access token Secret Manager reference"},
                "config": {"type": "OBJECT", "description": "New connection configuration dictionary"},
                "old_credential": {"type": "STRING", "description": "Previous credential reference for rollback"},
                "old_config": {"type": "OBJECT", "description": "Previous configuration dictionary for rollback"}
            },
            "required": ["brand_id", "provider", "credential"]
        }
    },
    handler=_connection_rotate_secret_handler
)

registry.register_tool(
    name="presence_citation_audit",
    schema={
        "name": "presence_citation_audit",
        "title": "Run Citation Audit",
        "description": "Run an SEO citation/competitor audit for the brand.",
        "domain": "presence",
        "parameters": {
            "type": "OBJECT",
            "properties": {"competitors": {"type": "STRING", "description": "Space/comma-separated competitor domains"}},
            "required": [],
        },
    },
    handler=_presence_citation_audit_handler,
)


# ---------------------------------------------------------------- connectors (manual connect)
# Manual "connect a provider" actions for the console connector directory. The
# operator supplies a Secret Manager secret name (where the provider credentials
# already live) + config; each creates a GOVERNED Connection Op via the adapter
# (propose -> gate -> approve -> audit), never a raw-credential DB write.

def _grow_google_ads_connect_handler(tenant_id: str, brand_id: str, secret_ref: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="grow",
        action="grow.google.connect",
        params={"provider": "google-ads", "secret_ref": secret_ref, "config": {}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )]


def _grow_meta_connect_handler(tenant_id: str, brand_id: str, secret_ref: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="grow",
        action="grow.meta.connect",
        params={"provider": "meta-ads", "secret_ref": secret_ref, "config": {}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )]


def _presence_google_connect_handler(tenant_id: str, brand_id: str, secret_ref: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="presence",
        action="presence.google.connect",
        params={"provider": "google", "secret_ref": secret_ref, "config": {}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )]


def _presence_wordpress_connect_handler(tenant_id: str, brand_id: str, secret_ref: str, url: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="presence",
        action="presence.wordpress.connect",
        params={"provider": "wordpress", "secret_ref": secret_ref, "config": {"url": url}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )]


def _presence_web_connect_handler(tenant_id: str, brand_id: str, secret_ref: str, url: str) -> list[OpSpec]:
    return [OpSpec(
        tenant_id=tenant_id, brand_id=brand_id, domain="presence",
        action="presence.web.connect",
        params={"provider": "web", "secret_ref": secret_ref, "config": {"url": url}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )]


_SECRET_REF_PROP = {"type": "STRING", "description": "Secret Manager secret name holding the provider API credentials"}

registry.register_tool(
    name="grow_google_ads_connect",
    schema={
        "name": "grow_google_ads_connect",
        "title": "Connect Google Ads",
        "description": "Connect a Google Ads account.",
        "domain": "grow",
        "parameters": {"type": "OBJECT", "properties": {"secret_ref": _SECRET_REF_PROP}, "required": ["secret_ref"]},
    },
    handler=_grow_google_ads_connect_handler,
)

registry.register_tool(
    name="grow_meta_connect",
    schema={
        "name": "grow_meta_connect",
        "title": "Connect Meta Ads",
        "description": "Connect a Meta (Facebook/Instagram) Ads account.",
        "domain": "grow",
        "parameters": {"type": "OBJECT", "properties": {"secret_ref": _SECRET_REF_PROP}, "required": ["secret_ref"]},
    },
    handler=_grow_meta_connect_handler,
)

registry.register_tool(
    name="presence_google_connect",
    schema={
        "name": "presence_google_connect",
        "title": "Connect Google Search Console",
        "description": "Connect Google Search Console & Merchant Center.",
        "domain": "presence",
        "parameters": {"type": "OBJECT", "properties": {"secret_ref": _SECRET_REF_PROP}, "required": ["secret_ref"]},
    },
    handler=_presence_google_connect_handler,
)

registry.register_tool(
    name="presence_wordpress_connect",
    schema={
        "name": "presence_wordpress_connect",
        "title": "Connect WordPress Site",
        "description": "Connect a WordPress site.",
        "domain": "presence",
        "parameters": {
            "type": "OBJECT",
            "properties": {"url": {"type": "STRING", "description": "WordPress site URL"}, "secret_ref": _SECRET_REF_PROP},
            "required": ["url", "secret_ref"],
        },
    },
    handler=_presence_wordpress_connect_handler,
)

registry.register_tool(
    name="presence_web_connect",
    schema={
        "name": "presence_web_connect",
        "title": "Connect Website",
        "description": "Connect an existing website / headless app.",
        "domain": "presence",
        "parameters": {
            "type": "OBJECT",
            "properties": {"url": {"type": "STRING", "description": "Website URL"}, "secret_ref": _SECRET_REF_PROP},
            "required": ["url", "secret_ref"],
        },
    },
    handler=_presence_web_connect_handler,
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


# ---------------------------------------------------------------- premium marketing tool registrations

registry.register_tool(
    name="grow_value_engine_optimize",
    schema={
        "name": "grow_value_engine_optimize",
        "title": "Optimize Bidding Value Engine",
        "domain": "grow",
        "description": "Optimize Google Ads smart bidding using macro/micro conversion value mapping.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "campaign_id": {"type": "STRING"},
                "posture": {"type": "STRING", "description": "Strategic risk posture: conservative | balanced | aggressive"},
                "macro_value_minor": {"type": "INTEGER", "description": "Baseline macro-conversion value in minor units"},
                "micro_conversions": {
                    "type": "ARRAY",
                    "description": "List of audited micro-conversion funnel steps",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "description": "Step name, e.g. add_to_cart"},
                            "value_minor": {"type": "INTEGER", "description": "Assigned micro-value in minor units"},
                            "dropoff_rate": {"type": "NUMBER", "description": "funnel drop-off rate (0.0 to 1.0)"}
                        },
                        "required": ["name", "value_minor", "dropoff_rate"]
                    }
                }
            },
            "required": ["brand_id", "campaign_id", "posture", "macro_value_minor", "micro_conversions"]
        }
    },
    handler=_grow_value_engine_optimize_handler
)

registry.register_tool(
    name="presence_consent_mode_audit",
    schema={
        "name": "presence_consent_mode_audit",
        "title": "Audit Consent Mode v2",
        "domain": "presence",
        "description": "Run an automated diagnostic audit to verify Consent Mode v2 and tag health.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "url": {"type": "STRING", "description": "Storefront URL to crawl and audit"}
            },
            "required": ["brand_id", "url"]
        }
    },
    handler=_presence_consent_mode_audit_handler
)

registry.register_tool(
    name="grow_meridian_mmm_audit",
    schema={
        "name": "grow_meridian_mmm_audit",
        "title": "Run Meridian MMM Audit",
        "domain": "grow",
        "description": "Generate a CFO-ready Meridian Marketing Mix Model incrementality and budget defense report.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "lookback_days": {"type": "INTEGER", "description": "Days of historic media data to ingest (default: 90)"}
            },
            "required": ["brand_id"]
        }
    },
    handler=_grow_meridian_mmm_audit_handler
)


# ---------------------------------------------------------------- premium marketing tool registrations (Sprint 2)

registry.register_tool(
    name="manage_merchant_feed_shield",
    schema={
        "name": "manage_merchant_feed_shield",
        "title": "Merchant Feed Warning Shield",
        "domain": "manage",
        "description": "Scan multi-account Merchant Center feeds for policy issues to proactively prevent ad account suspensions.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "merchant_id": {"type": "INTEGER", "description": "Google Merchant Center Account ID"}
            },
            "required": ["brand_id", "merchant_id"]
        }
    },
    handler=_manage_merchant_feed_shield_handler
)

registry.register_tool(
    name="grow_programmatic_dv360_connect",
    schema={
        "name": "grow_programmatic_dv360_connect",
        "title": "Connect DV360 Programmatic Media",
        "domain": "grow",
        "description": "Connect a DV360 advertiser profile to synchronize high-intent custom segments.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "advertiser_id": {"type": "STRING", "description": "DV360 Advertiser ID"},
                "secret_ref": {"type": "STRING", "description": "Secret Manager secret name containing DV360 OAuth tokens"}
            },
            "required": ["brand_id", "advertiser_id", "secret_ref"]
        }
    },
    handler=_grow_programmatic_dv360_connect_handler
)

registry.register_tool(
    name="grow_ai_readiness_audit",
    schema={
        "name": "grow_ai_readiness_audit",
        "title": "Audit Campaign AI-Readiness",
        "domain": "grow",
        "description": "Audit connected search campaigns, clean match types, and consolidate into AI-ready assets.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "campaign_id": {"type": "STRING", "description": "Google Ads Campaign ID to audit"}
            },
            "required": ["brand_id", "campaign_id"]
        }
    },
    handler=_grow_ai_readiness_audit_handler
)

registry.register_tool(
    name="grow_youtube_creator_connect",
    schema={
        "name": "grow_youtube_creator_connect",
        "title": "Connect YouTube Creator Channel",
        "domain": "grow",
        "description": "Connect a YouTube creator channel and configure CTV/Shorts bidding guidelines.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "channel_id": {"type": "STRING", "description": "YouTube Channel ID (e.g. UC...)"}
            },
            "required": ["brand_id", "channel_id"]
        }
    },
    handler=_grow_youtube_creator_connect_handler
)


registry.register_tool(
    name="build_deliver",
    schema={
        "name": "build_deliver",
        "title": "Deliver Code Build",
        "domain": "build",
        "description": "Trigger an autonomous coding agent build to deliver a feature or style modification.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "brand_id": {"type": "STRING"},
                "intent": {"type": "STRING", "description": "Conversational modification intent (e.g., 'change hero color to blue')"},
                "repo": {"type": "STRING", "description": "Target Git repository URL (optional)"}
            },
            "required": ["brand_id", "intent"]
        }
    },
    handler=_build_deliver_handler
)

