"""Agency OS — Structured Context Constructor.

Formats active tenant state, financial performance metrics, trust scores, and
open reputation alerts into a structured prompt context block for AI decision agents.
"""

import typing

class ContextConstructor:
    """Constructs the system prompt context for downstream LLM decision runs."""

    def __init__(self):
        pass

    def construct_agent_context(
        self,
        tenant_id: str,
        brand_name: str,
        trust_score: float,
        autonomy_tier: int,
        financial_metrics: typing.Dict[str, float],
        open_alerts: typing.List[typing.Dict[str, typing.Any]]
    ) -> str:
        """Constructs a markdown prompt block encapsulating the current system state.

        Args:
            tenant_id: Tenant context database ID.
            brand_name: User-facing name of the brand.
            trust_score: Active calculated trust score (0-100).
            autonomy_tier: Autonomy level (0, 1, or 2).
            financial_metrics: Dictionary containing CM1, CM2, CM3, POAS, or AYI.
            open_alerts: List of currently unresolved alert payloads.

        Returns:
            A formatted markdown context prompt.
        """
        # Define directive templates based on autonomy tier
        if autonomy_tier == 2:
            directive = (
                "**DIRECTIVE: FULL AUTONOMY ENABLED**\n"
                "You are authorized to execute bid adjustments, budget reallocations, "
                "and offline conversion uploads directly to integrated ad network APIs "
                "without human-in-the-loop approval. Maintain optimal performance margins."
            )
        elif autonomy_tier == 1:
            directive = (
                "**DIRECTIVE: SEMI-AUTONOMY ENABLED**\n"
                "You are authorized to draft optimization recommendations, but you "
                "MUST write them to the `action_cards` table for manual review. "
                "Direct API executions are BLOCKED. Do not make direct network writes."
            )
        else:
            directive = (
                "**DIRECTIVE: SYSTEM LOCKED / SAFE MODE**\n"
                "The trust score has fallen below the operating threshold. Automated "
                "optimizations are disabled. You may ONLY inspect diagnostics and generate "
                "reconciliation plans. No automated changes will be deployed."
            )

        # Build metrics block
        metrics_block = ""
        for k, v in financial_metrics.items():
            metrics_block += f"- {k}: {v:.2f}\n"

        # Build alerts block
        alerts_block = ""
        if open_alerts:
            for idx, alert in enumerate(open_alerts, 1):
                alerts_block += (
                    f"{idx}. [{alert.get('alert_type', 'ALERT')}] "
                    f"{alert.get('message', 'No details available')}\n"
                )
        else:
            alerts_block = "*No open brand reputation or configuration alerts.*"

        # Construct final output
        context = (
            f"# Active Tenant Context\n"
            f"- **Tenant ID**: {tenant_id}\n"
            f"- **Brand Name**: {brand_name}\n"
            f"- **Trust Score**: {trust_score:.1f}/100.0\n"
            f"- **Autonomy Tier**: Tier {autonomy_tier}\n\n"
            f"## System Directives\n"
            f"{directive}\n\n"
            f"## Financial Performance Metrics\n"
            f"{metrics_block}\n"
            f"## Open Alerts & Incidents\n"
            f"{alerts_block}"
        )

        return context
