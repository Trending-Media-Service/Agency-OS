import logging
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from app.services.marketing import MockMarketingClient

logger = logging.getLogger(__name__)

class GrowAdapter(Adapter):
    domain = "grow"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans growth actions. Supports creating ad campaigns."""
        normalized = intent.strip().lower()
        words = normalized.split()

        if "campaign" in words or "ad" in words:
            # Parse campaign name: look for word after "campaign" or "name:"
            name = "summer-sale"
            if "campaign" in words:
                idx = words.index("campaign")
                if idx + 1 < len(words) and words[idx+1] not in ("create", "new", "budget", "bid"):
                    name = words[idx+1]
            elif "name" in words:
                idx = words.index("name")
                if idx + 1 < len(words):
                    name = words[idx+1]
                    
            # Clean name slug
            name_slug = re.sub(r'[^a-z0-9-]', '', name.replace("_", "-"))

            # Parse budget: look for number after "budget"
            budget_minor = 500_000 # Default 5000 INR
            if "budget" in words:
                idx = words.index("budget")
                if idx + 1 < len(words):
                    try:
                        # Parse budget, assume in INR, convert to minor
                        budget_minor = int(float(words[idx+1]) * 100)
                    except ValueError:
                        pass

            # Parse bid: look for number after "bid"
            bid_minor = 5_000 # Default 50 INR
            if "bid" in words:
                idx = words.index("bid")
                if idx + 1 < len(words):
                    try:
                        bid_minor = int(float(words[idx+1]) * 100)
                    except ValueError:
                        pass

            campaign_id = f"camp-{brand_id}-{name_slug}"

            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.campaign.create",
                    params={
                        "campaign_id": campaign_id,
                        "name": name_slug,
                        "budget_minor": budget_minor,
                        "bid_minor": bid_minor,
                        "provider": "google-ads"
                    },
                    severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(amount_minor=budget_minor, currency="INR"), # cost is the budget
                )
            ]
        return []

    def preview(self, op: OpSpec) -> PreviewArtifact:
        """Generates preview for growth actions."""
        if op.action == "grow.campaign.create":
            name = op.params.get("name")
            budget = op.params.get("budget_minor", 0) / 100
            bid = op.params.get("bid_minor", 0) / 100
            summary = f"Will create Google Ads campaign: {name}\nBudget: {budget:.2f} INR\nTarget Bid: {bid:.2f} INR\nCampaign ID: {op.params.get('campaign_id')}"
            return PreviewArtifact(kind="campaign_create_preview", summary=summary, detail=op.params)
        elif op.action == "grow.campaign.delete":
            summary = f"Will delete campaign: {op.params.get('campaign_id')}"
            return PreviewArtifact(kind="campaign_delete_preview", summary=summary, detail=op.params)
        elif op.action == "grow.reallocate_budget.apply":
            transfer = op.params.get("transfer_amount_minor", 0) / 100.0
            src = op.params.get("source_campaign_id")
            tgt = op.params.get("target_campaign_id")
            summary = f"Saga: Budget Reallocation\n  - Transfer {transfer:.2f} INR from {src} to {tgt} due to performance variance."
            return PreviewArtifact(kind="campaign_reallocate_preview", summary=summary, detail=op.params)
        elif op.action == "grow.campaign.update":
            budget = op.params.get("budget_minor", 0) / 100
            bid_part = ""
            if "bid_minor" in op.params:
                bid = op.params.get("bid_minor") / 100
                bid_part = f"\nTarget Bid: {bid:.2f} INR"
            summary = f"Will update campaign: {op.params.get('campaign_id')}\nNew Budget: {budget:.2f} INR{bid_part}"
            return PreviewArtifact(kind="campaign_update_preview", summary=summary, detail=op.params)
        return PreviewArtifact(kind="unknown_preview", summary="Unknown action", detail={})

    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult:
        """Executes campaign operations."""
        client = MockMarketingClient(provider=op.params.get("provider", "google-ads"))
        campaign_id = op.params.get("campaign_id")

        if op.action == "grow.campaign.create":
            name = op.params.get("name")
            budget = op.params.get("budget_minor")
            bid = op.params.get("bid_minor")
            
            ok = await client.create_campaign(campaign_id, name, budget, bid)
            if ok:
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} created successfully", "campaign_id": campaign_id})
            return ExecResult(ok=False, detail={"error": "Failed to create campaign"})
            
        elif op.action == "grow.campaign.update":
            budget = op.params.get("budget_minor")
            bid = op.params.get("bid_minor")
            ok = await client.update_campaign(campaign_id, budget, bid)
            if ok:
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} updated"})
            return ExecResult(ok=False, detail={"error": f"Failed to update campaign {campaign_id}"})
            
        elif op.action == "grow.campaign.delete":
            ok = await client.delete_campaign(campaign_id)
            if ok:
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} deleted"})
            return ExecResult(ok=False, detail={"error": f"Failed to delete campaign {campaign_id}"})
            
        return ExecResult(ok=False, detail={"error": f"Unknown action: {op.action}"})

    async def verify(self, op: OpSpec) -> VerifyResult:
        """Verifies campaign status."""
        campaign_id = op.params.get("campaign_id")
        client = MockMarketingClient(provider=op.params.get("provider", "google-ads"))

        if op.action == "grow.campaign.create":
            try:
                camp = await client.get_campaign(campaign_id)
                if camp and camp["status"] == "ACTIVE":
                    return VerifyResult(ok=True, checks={"campaign_active": True}, detail=camp)
                return VerifyResult(ok=False, checks={"campaign_active": False})
            except Exception as e:
                return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

        elif op.action == "grow.campaign.delete":
            try:
                camp = await client.get_campaign(campaign_id)
                if not camp:
                    return VerifyResult(ok=True, checks={"campaign_deleted": True})
                return VerifyResult(ok=False, checks={"campaign_deleted": False})
            except Exception as e:
                 return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

        elif op.action == "grow.campaign.update":
            try:
                camp = await client.get_campaign(campaign_id)
                expected_budget = op.params.get("budget_minor")
                if camp and camp["budget_minor"] == expected_budget:
                    return VerifyResult(ok=True, checks={"budget_updated": True}, detail=camp)
                return VerifyResult(ok=False, checks={"budget_updated": False})
            except Exception as e:
                return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

        return VerifyResult(ok=False, checks={})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        """Returns compensation Ops."""
        if op.action == "grow.campaign.create":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="grow.campaign.delete",
                    params={
                        "campaign_id": op.params.get("campaign_id"),
                        "provider": op.params.get("provider")
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    parent_op_id=op.id
                )
            ]
        elif op.action == "grow.campaign.update":
            prev_budget = op.params.get("previous_budget_minor")
            if prev_budget is not None:
                return [
                    OpSpec(
                        tenant_id=op.tenant_id,
                        brand_id=op.brand_id,
                        domain=self.domain,
                        action="grow.campaign.update",
                        params={
                            "campaign_id": op.params.get("campaign_id"),
                            "provider": op.params.get("provider"),
                            "budget_minor": prev_budget,
                            "bid_minor": op.params.get("bid_minor")
                        },
                        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
                        parent_op_id=op.id
                    )
                ]
        return []
