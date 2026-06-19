"""Scaffold stubs for other Tier 1 integrations.

All classes inherit from ProviderAdapter and return healthy mock results.
These act as clean templates for future expansion.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.integrations.base import ProviderAdapter, HealthCheckResult, WebhookEvent

logger = logging.getLogger(__name__)


class GoogleAdsAdapter(ProviderAdapter):
    """Stub adapter for Google Ads API."""

    def _validate_config(self):
        if "developer_token" not in self.config:
            raise ValueError("Google Ads config missing required key: 'developer_token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("Google Ads connection test: [STUB] Successful")
        return HealthCheckResult(provider="google-ads", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        impressions = random.randint(15000, 60000)
        clicks = int(impressions * random.uniform(0.015, 0.045))
        spend = clicks * random.uniform(8.0, 18.0)
        
        mock_data = {
            "impressions": impressions,
            "clicks": clicks,
            "spend": round(spend, 2),
            "conversions": int(clicks * random.uniform(0.03, 0.08)),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        campaign_id = payload.get("campaign_id")
        logger.info(f"Google Ads [STUB] Action: {action} on campaign {campaign_id}")
        return {"status": "success", "campaign_id": campaign_id, "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return WebhookEvent(
            provider="google-ads",
            event_type="google-ads.stub_event",
            timestamp=datetime.utcnow(),
            data={"raw_body": raw_body}
        )


class YouTubeAdapter(ProviderAdapter):
    """Stub adapter for YouTube Data API v3."""

    def _validate_config(self):
        if "api_key" not in self.config and "token" not in self.config:
            raise ValueError("YouTube config requires either 'api_key' or OAuth 'token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("YouTube connection test: [STUB] Successful")
        return HealthCheckResult(provider="youtube", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        mock_data = {
            "views": random.randint(1000, 10000),
            "likes": random.randint(50, 500),
            "comments": random.randint(5, 50),
            "shares": random.randint(10, 100),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"YouTube [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return None


class LinkedInAdapter(ProviderAdapter):
    """Stub adapter for LinkedIn Marketing Solutions API."""

    def _validate_config(self):
        if "token" not in self.config:
            raise ValueError("LinkedIn config missing required key: 'token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("LinkedIn connection test: [STUB] Successful")
        return HealthCheckResult(provider="linkedin", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        mock_data = {
            "impressions": random.randint(5000, 20000),
            "clicks": random.randint(100, 800),
            "spend": round(random.uniform(50.0, 500.0), 2),
            "conversions": random.randint(5, 30),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"LinkedIn [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return None


class XAdapter(ProviderAdapter):
    """Stub adapter for X (Twitter) API v2."""

    def _validate_config(self):
        if "consumer_key" not in self.config:
            raise ValueError("X config missing required key: 'consumer_key'")

    async def connect(self) -> HealthCheckResult:
        logger.info("X connection test: [STUB] Successful")
        return HealthCheckResult(provider="x", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        mock_data = {
            "impressions": random.randint(1000, 5000),
            "engagements": random.randint(50, 250),
            "likes": random.randint(10, 100),
            "retweets": random.randint(2, 20),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"X [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return None


class TikTokAdapter(ProviderAdapter):
    """Stub adapter for TikTok Business API."""

    def _validate_config(self):
        if "token" not in self.config:
            raise ValueError("TikTok config missing required key: 'token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("TikTok connection test: [STUB] Successful")
        return HealthCheckResult(provider="tiktok", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        mock_data = {
            "views": random.randint(50000, 200000),
            "clicks": random.randint(500, 3000),
            "spend": round(random.uniform(100.0, 1000.0), 2),
            "conversions": random.randint(10, 100),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"TikTok [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return None


class SlackAdapter(ProviderAdapter):
    """Stub adapter for Slack Web API / Events."""

    def _validate_config(self):
        if "token" not in self.config:
            raise ValueError("Slack config missing required key: 'token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("Slack connection test: [STUB] Successful")
        return HealthCheckResult(provider="slack", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        return {}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Slack [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return WebhookEvent(
            provider="slack",
            event_type="slack.event",
            timestamp=datetime.utcnow(),
            data={"raw_body": raw_body}
        )


class HubSpotAdapter(ProviderAdapter):
    """Stub adapter for HubSpot CRM/Marketing API."""

    def _validate_config(self):
        if "token" not in self.config:
            raise ValueError("HubSpot config missing required key: 'token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("HubSpot connection test: [STUB] Successful")
        return HealthCheckResult(provider="hubspot", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        mock_data = {
            "contacts_created": random.randint(5, 50),
            "emails_opened": random.randint(100, 1000),
            "deals_won": random.randint(1, 5),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"HubSpot [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return None


class SalesforceAdapter(ProviderAdapter):
    """Stub adapter for Salesforce REST API."""

    def _validate_config(self):
        if "instance_url" not in self.config:
            raise ValueError("Salesforce config missing required key: 'instance_url'")

    async def connect(self) -> HealthCheckResult:
        logger.info("Salesforce connection test: [STUB] Successful")
        return HealthCheckResult(provider="salesforce", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        return {}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Salesforce [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return None


class StripeAdapter(ProviderAdapter):
    """Stub adapter for Stripe API."""

    def _validate_config(self):
        # Stripe uses a secret token/key
        if "token" not in self.config:
            raise ValueError("Stripe config missing required key: 'token'")

    async def connect(self) -> HealthCheckResult:
        logger.info("Stripe connection test: [STUB] Successful")
        return HealthCheckResult(provider="stripe", is_healthy=True, status_code=200)

    async def health_check(self) -> HealthCheckResult:
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        import random
        mock_data = {
            "volume_minor": random.randint(100000, 1000000), # minor units
            "charges_count": random.randint(10, 100),
            "refunds_minor": random.randint(0, 5000),
        }
        return {k: mock_data.get(k, 0) for k in metric_keys}

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Stripe [STUB] Action: {action}")
        return {"status": "success", "action_executed": action, "stub": True}

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        return WebhookEvent(
            provider="stripe",
            event_type="stripe.charge.succeeded",
            timestamp=datetime.utcnow(),
            data={"amount": 1500, "currency": "usd"}
        )
