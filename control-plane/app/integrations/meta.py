"""Meta (Facebook/Instagram) provider adapter implementation.

Uses raw asynchronous httpx calls to the Meta Graph API to maintain a
fully non-blocking, zero-dependency footprint. Supports high-fidelity mocks
when in test mode or when mock credentials are provided.
"""

import hashlib
import hmac
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

from app.integrations.base import ProviderAdapter, HealthCheckResult, WebhookEvent

logger = logging.getLogger(__name__)


class MetaAdapter(ProviderAdapter):
    """Adapter for Meta Ads (Facebook/Instagram) Graph & Marketing APIs."""

    def _validate_config(self):
        """Validate required config keys are present."""
        # Meta Ads requires an Access Token and an Ad Account ID
        if "token" not in self.config:
            raise ValueError("Meta config missing required key: 'token'")
        if "ad_account_id" not in self.config:
            raise ValueError("Meta config missing required key: 'ad_account_id'")

        self.token = self.config["token"]
        self.ad_account_id = self.config["ad_account_id"]
        self.app_secret = self.config.get("app_secret")

        # Determine if we are in mock mode
        import os
        env = os.getenv("AOS_ENV", "development")
        self._is_mock = env == "test" or self.token == "mock-meta-token" or self.token.startswith("mock-")

    async def connect(self) -> HealthCheckResult:
        """Test connection to Meta Graph API."""
        if self._is_mock:
            logger.info("Meta connection test: [MOCK] Successful")
            return HealthCheckResult(provider="meta", is_healthy=True, status_code=200)

        # Build Graph API URL to fetch ad account details
        url = f"https://graph.facebook.com/v20.0/{self.ad_account_id}"
        params = {
            "fields": "name,account_status,currency",
            "access_token": self.token
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, params=params)
                self._log_request("GET", url, resp.status_code)
                
                if resp.status_code == 200:
                    return HealthCheckResult(provider="meta", is_healthy=True, status_code=200)
                
                err_msg = resp.json().get("error", {}).get("message", "Unknown Graph API error")
                return HealthCheckResult(
                    provider="meta", 
                    is_healthy=False, 
                    status_code=resp.status_code, 
                    error_message=err_msg
                )
            except Exception as e:
                logger.error(f"Meta Graph API connection failed: {e}")
                return HealthCheckResult(
                    provider="meta", 
                    is_healthy=False, 
                    error_message=str(e)
                )

    async def health_check(self) -> HealthCheckResult:
        """Periodic health check (reuses connect)."""
        return await self.connect()

    async def fetch_metrics(self, resource_id: str, metric_keys: List[str]) -> Dict[str, Any]:
        """Fetch insights/metrics for a campaign, adset, or ad account.
        
        Args:
            resource_id: Platform resource ID (e.g., campaign ID, 'act_12345678').
            metric_keys: List of metrics (e.g., impressions, clicks, spend, conversions).
        """
        if self._is_mock:
            # High-fidelity mock metrics
            import random
            impressions = random.randint(10000, 50000)
            clicks = int(impressions * random.uniform(0.01, 0.05))
            spend = clicks * random.uniform(5.0, 15.0)
            conversions = int(clicks * random.uniform(0.02, 0.10))
            
            mock_data = {
                "impressions": impressions,
                "clicks": clicks,
                "spend": round(spend, 2),
                "conversions": conversions,
                "ctr": round(clicks / impressions * 100, 2) if impressions > 0 else 0.0,
                "cpc": round(spend / clicks, 2) if clicks > 0 else 0.0,
            }
            return {k: mock_data.get(k, 0) for k in metric_keys}

        # Query the Meta Insights endpoint
        # E.g., https://graph.facebook.com/v20.0/{resource_id}/insights
        url = f"https://graph.facebook.com/v20.0/{resource_id}/insights"
        
        # Translate unified metric keys to Meta Graph API field names
        meta_fields = []
        for key in metric_keys:
            if key in ("impressions", "clicks", "spend"):
                meta_fields.append(key)
            elif key == "conversions":
                meta_fields.append("actions")
        
        if not meta_fields:
            meta_fields = ["impressions", "clicks", "spend"]

        params = {
            "fields": ",".join(meta_fields),
            "date_preset": "last_30d",
            "access_token": self.token
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, params=params)
                self._log_request("GET", url, resp.status_code)
                
                if resp.status_code != 200:
                    err_msg = resp.json().get("error", {}).get("message", "Failed to fetch insights")
                    raise RuntimeError(f"Meta Graph API Error: {err_msg}")
                
                data = resp.json().get("data", [])
                if not data:
                    return {k: 0 for k in metric_keys}
                
                # Parse Meta response
                insights = data[0]
                results = {}
                
                if "impressions" in metric_keys:
                    results["impressions"] = int(insights.get("impressions", 0))
                if "clicks" in metric_keys:
                    results["clicks"] = int(insights.get("clicks", 0))
                if "spend" in metric_keys:
                    results["spend"] = float(insights.get("spend", 0.0))
                if "conversions" in metric_keys:
                    # Meta returns conversions inside 'actions' array of dicts
                    actions = insights.get("actions", [])
                    conversions = 0
                    for action in actions:
                        if action.get("action_type") in ("offsite_conversion.custom", "purchase"):
                            conversions += int(action.get("value", 0))
                    results["conversions"] = conversions
                    
                # Fill missing keys with 0
                for k in metric_keys:
                    if k not in results:
                        results[k] = 0
                        
                return results

            except Exception as e:
                logger.error(f"Failed to fetch insights from Meta: {e}")
                raise

    async def send_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send an action to the Meta Ads API (e.g. pause_campaign, resume_campaign, update_budget)."""
        campaign_id = payload.get("campaign_id")
        if not campaign_id:
            raise ValueError("Meta send_action payload missing 'campaign_id'")

        if self._is_mock:
            logger.info(f"Meta [MOCK] Action: {action} on campaign {campaign_id}")
            return {"status": "success", "campaign_id": campaign_id, "action_executed": action}

        # Map unified action names to Meta API parameters
        url = f"https://graph.facebook.com/v20.0/{campaign_id}"
        post_data: Dict[str, Any] = {
            "access_token": self.token
        }

        if action == "pause_campaign":
            post_data["status"] = "PAUSED"
        elif action == "resume_campaign":
            post_data["status"] = "ACTIVE"
        elif action == "update_budget":
            budget_minor = payload.get("budget_minor")
            if budget_minor is None:
                raise ValueError("Meta update_budget action requires 'budget_minor'")
            # Meta Ads API accepts budget in standard units (decimal string, e.g. "150.00")
            post_data["daily_budget"] = f"{budget_minor / 100:.2f}"
        else:
            raise ValueError(f"Unsupported action for Meta adapter: {action}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(url, data=post_data)
                self._log_request("POST", url, resp.status_code)
                
                if resp.status_code == 200 and resp.json().get("success"):
                    return {"status": "success", "campaign_id": campaign_id, "meta_response": resp.json()}
                
                err_msg = resp.json().get("error", {}).get("message", "Failed to execute action on Meta Graph API")
                raise RuntimeError(f"Meta Graph API Error: {err_msg}")
            except Exception as e:
                logger.error(f"Failed to send action to Meta: {e}")
                raise

    async def handle_webhook(self, raw_body: str, signature: str) -> Optional[WebhookEvent]:
        """Verify Meta Hub/X-Hub-Signature-256 signature and parse event."""
        # Meta webhooks are signed using HMAC-SHA256 of the raw payload using the App Secret
        if self.app_secret and signature:
            expected_sig = signature
            if expected_sig.startswith("sha256="):
                expected_sig = expected_sig[7:]

            computed = hmac.new(
                self.app_secret.encode("utf-8"),
                raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(computed, expected_sig):
                logger.warning("Meta Webhook Signature Mismatch!")
                return None

        # Parse webhook JSON payload
        import json
        try:
            payload = json.loads(raw_body)
            # Normalize event type
            entry = payload.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            event_type = changes.get("field", "unknown_change")
            
            return WebhookEvent(
                provider="meta",
                event_type=f"meta.{event_type}",
                timestamp=datetime.utcfromtimestamp(entry.get("time", datetime.utcnow().timestamp())),
                data=changes.get("value", {}),
                raw_body=raw_body
            )
        except Exception as e:
            logger.error(f"Failed to parse Meta webhook payload: {e}")
            return None
