"""Agency OS — Mock API Server (Next.js Endpoint Simulation).

Provides route mapping and response handling simulating Next.js backend API
handlers to verify UI interaction endpoints.
"""

import typing
from google3.learning.gemini.agents.projects.agency_os import autonomy_runner

class MockApiServer:
    """Simulates API routes for backend integrations and audit sweeps."""

    def __init__(self, runner: autonomy_runner.AutonomyGraduationRunner):
        self.runner = runner
        # Mock database tenant state
        self.tenant_state = {
            "tenant_id": "tenant-abc",
            "brand_name": "Abley",
            "gtm_present": True,
            "pixel_present": True,
            "capi_dedup_rate": 0.98,
            "gmc_critical_mismatch_count": 0,
            "gmc_warning_count": 1,
            "reputation_alert_count": 0,
            "financial_metrics": {"CM1": 12000.0, "POAS": 1.4},
            "open_alerts": [],
        }

    def route_request(
        self,
        method: str,
        path: str,
        payload: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Tuple[int, typing.Dict[str, typing.Any]]:
        """Routes simulated HTTP requests to correct mock controller endpoints.

        Args:
            method: HTTP verb (GET, POST).
            path: Relative URI.
            payload: JSON request body dict.

        Returns:
            Tuple of (HTTP status code, JSON response dict).
        """
        method = method.upper()

        if method == "GET" and path == "/api/v1/integrations":
            return 200, {
                "status": "success",
                "integrations": [
                    {"name": "google_ads", "connected": True},
                    {"name": "facebook_ads", "connected": True},
                    {"name": "shopify", "connected": True},
                    {"name": "google_merchant_center", "connected": True}
                ]
            }

        elif method == "POST" and path == "/api/v1/sweep":
            proposed = payload.get("proposed_cards", []) if payload else []
            results = self.runner.run_autonomy_cycle(
                tenant_id=self.tenant_state["tenant_id"],
                brand_name=self.tenant_state["brand_name"],
                gtm_present=self.tenant_state["gtm_present"],
                pixel_present=self.tenant_state["pixel_present"],
                capi_dedup_rate=self.tenant_state["capi_dedup_rate"],
                gmc_critical_mismatch_count=self.tenant_state[
                    "gmc_critical_mismatch_count"
                ],
                gmc_warning_count=self.tenant_state["gmc_warning_count"],
                reputation_alert_count=self.tenant_state["reputation_alert_count"],
                financial_metrics=self.tenant_state["financial_metrics"],
                open_alerts=self.tenant_state["open_alerts"],
                proposed_cards=proposed
            )
            return 200, {
                "status": "completed",
                "trust_score": results.trust_score,
                "autonomy_tier": results.autonomy_tier,
                "lockout_active": results.lockout_active,
                "processed_cards": results.processed_cards
            }

        elif method == "GET" and path == "/api/v1/autonomy":
            score = self.runner.ats_calc.calculate_score(
                self.tenant_state["gtm_present"],
                self.tenant_state["pixel_present"],
                self.tenant_state["capi_dedup_rate"],
                self.tenant_state["gmc_critical_mismatch_count"],
                self.tenant_state["gmc_warning_count"],
                self.tenant_state["reputation_alert_count"]
            )
            tier = self.runner.ats_calc.resolve_autonomy_tier(score)
            return 200, {
                "status": "success",
                "trust_score": score,
                "autonomy_tier": tier
            }

        elif method == "POST" and path == "/api/v1/auth/ticket":
            username = payload.get("username", "unknown") if payload else "unknown"
            return 201, {
                "status": "authorized",
                "ticket_id": f"ticket_mock_hash_{username}_123",
                "expires_in_sec": 3600
            }

        return 404, {"error": f"Endpoint not found: {method} {path}"}
