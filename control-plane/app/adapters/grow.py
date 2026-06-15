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
        """Plans growth actions. Supports creating ad campaigns, adjusting bids, pausing campaigns, and alerts."""
        normalized = intent.strip().lower()
        words = normalized.split()

        if "alert" in words:
            alert_idx = words.index("alert")
            msg = " ".join(words[alert_idx+1:])
            if not msg:
                msg = "System alert dispatch requested"
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.alert.dispatch",
                    params={
                        "message": msg
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    cost_estimate=Money(amount_minor=0, currency="INR")
                )
            ]

        if "pause" in words:
            # Parse campaign_id: look for word starting with "camp-" or after "campaign"
            campaign_id = "camp-default"
            for w in words:
                if w.startswith("camp-"):
                    campaign_id = w
                    break
            if campaign_id == "camp-default" and "campaign" in words:
                idx = words.index("campaign")
                if idx + 1 < len(words):
                    campaign_id = words[idx+1]

            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.campaign.pause",
                    params={
                        "campaign_id": campaign_id,
                        "provider": "google-ads"
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE), # Can resume campaign
                    cost_estimate=Money(amount_minor=0, currency="INR")
                )
            ]

        if "resume" in words:
            # Parse campaign_id: look for word starting with "camp-" or after "campaign"
            campaign_id = "camp-default"
            for w in words:
                if w.startswith("camp-"):
                    campaign_id = w
                    break
            if campaign_id == "camp-default" and "campaign" in words:
                idx = words.index("campaign")
                if idx + 1 < len(words):
                    campaign_id = words[idx+1]

            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.campaign.resume",
                    params={
                        "campaign_id": campaign_id,
                        "provider": "google-ads"
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE), # Can pause campaign
                    cost_estimate=Money(amount_minor=0, currency="INR")
                )
            ]

        if "bid" in words and ("adjust" in words or "set" in words or "update" in words):
            # Parse campaign_id: look for word starting with "camp-" or after "campaign"
            campaign_id = "camp-default"
            for w in words:
                if w.startswith("camp-"):
                    campaign_id = w
                    break
            if campaign_id == "camp-default" and "campaign" in words:
                idx = words.index("campaign")
                if idx + 1 < len(words):
                    campaign_id = words[idx+1]

            # Parse new bid: look for number after "to" or "bid"
            new_bid_minor = 5_000 # default 50 INR
            for idx, w in enumerate(words):
                if w in ("to", "bid") and idx + 1 < len(words):
                    try:
                        new_bid_minor = int(float(words[idx+1]) * 100)
                    except ValueError:
                        pass

            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.bid.adjust",
                    params={
                        "campaign_id": campaign_id,
                        "new_bid_minor": new_bid_minor,
                        "previous_bid_minor": 5_000, # default fallback
                        "provider": "google-ads"
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(amount_minor=0, currency="INR")
                )
            ]

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
        elif op.action == "grow.budget.reallocate":
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
        elif op.action == "grow.bid.adjust":
            bid = op.params.get("new_bid_minor", 0) / 100
            summary = f"Will adjust bid for campaign: {op.params.get('campaign_id')}\nNew Target Bid: {bid:.2f} INR"
            return PreviewArtifact(kind="campaign_bid_adjust_preview", summary=summary, detail=op.params)
        elif op.action == "grow.campaign.pause":
            summary = f"Will pause campaign: {op.params.get('campaign_id')}"
            return PreviewArtifact(kind="campaign_pause_preview", summary=summary, detail=op.params)
        elif op.action == "grow.campaign.resume":
            summary = f"Will resume campaign: {op.params.get('campaign_id')}"
            return PreviewArtifact(kind="campaign_resume_preview", summary=summary, detail=op.params)
        elif op.action == "grow.alert.dispatch":
            summary = f"ALERT DISPATCH:\n{op.params.get('message')}"
            return PreviewArtifact(kind="alert_dispatch_preview", summary=summary, detail=op.params)
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
            
        elif op.action == "grow.bid.adjust":
            new_bid = op.params.get("new_bid_minor")
            ok = await client.update_campaign(campaign_id, bid_minor=new_bid)
            if ok:
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} bid adjusted to {new_bid}"})
            return ExecResult(ok=False, detail={"error": f"Failed to adjust bid for campaign {campaign_id}"})
            
        elif op.action == "grow.campaign.pause":
            ok = await client.update_campaign(campaign_id, status="PAUSED")
            if ok:
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} paused"})
            return ExecResult(ok=False, detail={"error": f"Failed to pause campaign {campaign_id}"})
            
        elif op.action == "grow.campaign.resume":
            ok = await client.update_campaign(campaign_id, status="ACTIVE")
            if ok:
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} resumed"})
            return ExecResult(ok=False, detail={"error": f"Failed to resume campaign {campaign_id}"})
            
        elif op.action == "grow.alert.dispatch":
            logger.info(f"ALERT DISPATCHED: {op.params.get('message')}")
            return ExecResult(ok=True, detail={"message": "Alert dispatched"})
            
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
        elif op.action == "grow.bid.adjust":
            try:
                camp = await client.get_campaign(campaign_id)
                expected_bid = op.params.get("new_bid_minor")
                if camp and camp["bid_minor"] == expected_bid:
                    return VerifyResult(ok=True, checks={"bid_adjusted": True}, detail=camp)
                return VerifyResult(ok=False, checks={"bid_adjusted": False})
            except Exception as e:
                return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

        elif op.action == "grow.campaign.pause":
            try:
                camp = await client.get_campaign(campaign_id)
                if camp and camp["status"] == "PAUSED":
                    return VerifyResult(ok=True, checks={"campaign_paused": True}, detail=camp)
                return VerifyResult(ok=False, checks={"campaign_paused": False})
            except Exception as e:
                return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

        elif op.action == "grow.campaign.resume":
            try:
                camp = await client.get_campaign(campaign_id)
                if camp and camp["status"] == "ACTIVE":
                    return VerifyResult(ok=True, checks={"campaign_resumed": True}, detail=camp)
                return VerifyResult(ok=False, checks={"campaign_resumed": False})
            except Exception as e:
                return VerifyResult(ok=False, checks={}, detail={"error": str(e)})

        elif op.action == "grow.alert.dispatch":
            return VerifyResult(ok=True, checks={"alert_dispatched": True})

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
        elif op.action == "grow.bid.adjust":
            prev_bid = op.params.get("previous_bid_minor")
            if prev_bid is not None:
                return [
                    OpSpec(
                        tenant_id=op.tenant_id,
                        brand_id=op.brand_id,
                        domain=self.domain,
                        action="grow.bid.adjust",
                        params={
                            "campaign_id": op.params.get("campaign_id"),
                            "provider": op.params.get("provider"),
                            "new_bid_minor": prev_bid,
                            "previous_bid_minor": op.params.get("new_bid_minor")
                        },
                        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                        parent_op_id=op.id
                    )
                ]
        elif op.action == "grow.campaign.pause":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="grow.campaign.resume",
                    params={
                        "campaign_id": op.params.get("campaign_id"),
                        "provider": op.params.get("provider")
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=op.id
                )
            ]
        elif op.action == "grow.campaign.resume":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="grow.campaign.pause",
                    params={
                        "campaign_id": op.params.get("campaign_id"),
                        "provider": op.params.get("provider")
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    parent_op_id=op.id
                )
            ]
        return []
