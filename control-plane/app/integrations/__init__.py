"""Integrations module for external providers and platforms.

Exposes the base class, standard response structures, and a factory to
dynamically resolve and instantiate the correct provider adapter.
"""

from app.integrations.base import ProviderAdapter, HealthCheckResult, WebhookEvent
from app.integrations.meta import MetaAdapter
from app.integrations.stubs import (
    GoogleAdsAdapter,
    YouTubeAdapter,
    LinkedInAdapter,
    XAdapter,
    TikTokAdapter,
    SlackAdapter,
    HubSpotAdapter,
    SalesforceAdapter,
    StripeAdapter
)

# Registry mapping provider identifier to its adapter class
_REGISTRY = {
    "meta-ads": MetaAdapter,
    "meta": MetaAdapter,
    "google-ads": GoogleAdsAdapter,
    "youtube": YouTubeAdapter,
    "linkedin": LinkedInAdapter,
    "x": XAdapter,
    "tiktok": TikTokAdapter,
    "slack": SlackAdapter,
    "hubspot": HubSpotAdapter,
    "salesforce": SalesforceAdapter,
    "stripe": StripeAdapter
}


def get_provider_adapter(provider: str, config: dict) -> ProviderAdapter:
    """Factory function to instantiate and return a ProviderAdapter.
    
    Args:
        provider: Provider identifier (e.g., 'meta', 'google-ads', 'stripe').
        config: Connection configuration parameters (e.g. credentials, tokens, URLs).
        
    Returns:
        An instantiated ProviderAdapter subclass.
    """
    adapter_cls = _REGISTRY.get(provider.lower())
    if not adapter_cls:
        raise ValueError(f"Unsupported provider integration: {provider}")
    return adapter_cls(config)


__all__ = [
    "ProviderAdapter",
    "HealthCheckResult",
    "WebhookEvent",
    "MetaAdapter",
    "GoogleAdsAdapter",
    "YouTubeAdapter",
    "LinkedInAdapter",
    "XAdapter",
    "TikTokAdapter",
    "SlackAdapter",
    "HubSpotAdapter",
    "SalesforceAdapter",
    "StripeAdapter",
    "get_provider_adapter"
]
