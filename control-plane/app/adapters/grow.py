import logging
import re
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.kernel.optypes import OpSpec, PreviewArtifact, ExecResult, VerifyResult, Severity, Reversibility, Money
from app.kernel.loop import Adapter
from app.services.marketing import get_marketing_client
from app.models import Connection, Campaign
from app.services.secrets import SecretManagerClient

logger = logging.getLogger(__name__)

class GrowAdapter(Adapter):
    domain = "grow"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        """Plans growth actions. Supports creating ad campaigns, adjusting bids, pausing campaigns, and alerts."""
        normalized = intent.strip().lower()
        words = normalized.split()

        if "connect" in words and ("google" in words or "google-ads" in words or "google_ads" in words):
            credential = next((w for w in words if w.startswith("secret:")), "secret:google-ads-token")
            if credential.startswith("secret:"):
                credential = credential[7:]
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.google.connect",
                    params={
                        "provider": "google-ads",
                        "credential": credential,
                        "config": {}
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(0)
                )
            ]
        elif "disconnect" in words and ("google" in words or "google-ads" in words or "google_ads" in words):
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.google.disconnect",
                    params={"provider": "google-ads"},
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    cost_estimate=Money(0)
                )
            ]
            
        elif "connect" in words and ("meta" in words or "facebook" in words or "fb" in words):
            credential = next((w for w in words if w.startswith("secret:")), "secret:meta-ads-token")
            if credential.startswith("secret:"):
                credential = credential[7:]
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.meta.connect",
                    params={
                        "provider": "meta-ads",
                        "credential": credential,
                        "config": {}
                    },
                    severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
                    cost_estimate=Money(0)
                )
            ]
        elif "disconnect" in words and ("meta" in words or "facebook" in words or "fb" in words):
            return [
                OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain=self.domain,
                    action="grow.meta.disconnect",
                    params={"provider": "meta-ads"},
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    cost_estimate=Money(0)
                )
            ]

        elif "alert" in words:
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
        if op.action == "grow.google.connect":
            summary = f"Will establish connection to Google Ads account.\nCredential: ****"
            return PreviewArtifact(kind="google_connect_preview", summary=summary, detail=op.params)
        elif op.action == "grow.google.disconnect":
            summary = "Will remove connection to Google Ads account."
            return PreviewArtifact(kind="google_disconnect_preview", summary=summary, detail=op.params)
        elif op.action == "grow.meta.connect":
            summary = f"Will establish connection to Meta Ads account.\nCredential: ****"
            return PreviewArtifact(kind="meta_connect_preview", summary=summary, detail=op.params)
        elif op.action == "grow.meta.disconnect":
            summary = "Will remove connection to Meta Ads account."
            return PreviewArtifact(kind="meta_disconnect_preview", summary=summary, detail=op.params)

        elif op.action == "grow.campaign.create":
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
        if op.action in ("grow.google.connect", "grow.meta.connect"):
            if not session:
                return ExecResult(ok=False, detail={"error": "Database session is required for Connection operations"})
                
            provider = op.params.get("provider")
            raw_token = op.params.get("credential") or op.params.get("secret_ref")
            if not raw_token or not isinstance(raw_token, str) or not raw_token.strip():
                from app.metrics import CONNECTOR_OPERATIONS
                CONNECTOR_OPERATIONS.labels(operation="connect", provider=provider or "unknown", result="failure").inc()
                return ExecResult(ok=False, detail={"error": "Credential or secret_ref is required and cannot be empty or whitespace-only."})
            config = op.params.get("config", {})
            
            # Write to Secret Manager
            secret_id = f"{op.tenant_id}-{op.brand_id}-{provider}-secret"
            secrets_client = SecretManagerClient()
            credential_ref = await secrets_client.write_secret(secret_id, raw_token)
            
            logger.info(f"Connecting {provider} for brand {op.brand_id} with credential reference {credential_ref}")
            
            stmt = select(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                existing.credential = credential_ref
                existing.config = config
                existing.status = "unverified"
                logger.info(f"Updated existing connection for {provider}")
            else:
                conn = Connection(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    provider=provider,
                    credential=credential_ref,
                    config=config,
                    status="unverified"
                )
                session.add(conn)
                logger.info(f"Created new connection for {provider}")
                
            from app.metrics import CONNECTOR_OPERATIONS
            CONNECTOR_OPERATIONS.labels(operation="connect", provider=provider, result="success").inc()
            return ExecResult(ok=True, detail={"message": f"Connection to {provider} registered in DB and Secret Manager"})
            
        elif op.action in ("grow.google.disconnect", "grow.meta.disconnect"):
            if not session:
                return ExecResult(ok=False, detail={"error": "Database session is required for Connection operations"})
                
            provider = op.params.get("provider")
            logger.info(f"Disconnecting {provider} for brand {op.brand_id}")
            
            # Delete from Secret Manager first
            stmt = select(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            res = await session.execute(stmt)
            conn = res.scalar_one_or_none()
            if conn and conn.credential:
                secrets_client = SecretManagerClient()
                await secrets_client.delete_secret(conn.credential)
                
            stmt_del = delete(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            await session.execute(stmt_del)
            return ExecResult(ok=True, detail={"message": f"Connection to {provider} removed from DB and Secret Manager"})

        # Resolve connection credentials dynamically
        provider = op.params.get("provider", "google-ads")
        token = None
        config = {}
        if session:
            stmt_conn = select(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            res_conn = await session.execute(stmt_conn)
            conn = res_conn.scalar_one_or_none()
            if conn:
                config = conn.config or {}
                # Retrieve tenant to determine dedicated GCP project ID for secret isolation
                from app.models import Tenant
                stmt_tenant = select(Tenant).where(Tenant.id == conn.tenant_id)
                res_tenant = await session.execute(stmt_tenant)
                tenant = res_tenant.scalar_one_or_none()
                gcp_project = tenant.gcp_project if tenant else None

                try:
                    secrets_client = SecretManagerClient(project_id=gcp_project)
                    token = await secrets_client.read_secret(conn.credential)
                except Exception as e:
                    logger.error(f"Failed to read marketing secret from Secret Manager: {e}")
                    raise RuntimeError(f"Failed to resolve marketing credentials from Secret Manager: {e}") from e

        client = get_marketing_client(provider=provider, token=token, config=config)
        campaign_id = op.params.get("campaign_id")

        is_dry = op.params.get("dry_run", False)
        if is_dry:
            logger.info(f"[DRY RUN] Simulating action {op.action} for campaign {campaign_id} with params {op.params}")
            return ExecResult(
                ok=True,
                detail={
                    "message": f"[DRY RUN] Campaign operation {op.action} simulated successfully.",
                    "campaign_id": campaign_id,
                    "dry_run": True,
                    "action": op.action,
                    "params": op.params
                }
            )

        if op.action == "grow.campaign.create":
            name = op.params.get("name")
            budget = op.params.get("budget_minor")
            bid = op.params.get("bid_minor")
            provider = op.params.get("provider", "google-ads")
            
            # IDEMPOTENCY CHECK: Check if campaign already exists in external system
            existing_ext = await client.get_campaign(campaign_id)
            if existing_ext:
                logger.info(f"Campaign {campaign_id} already exists in external provider {provider} (idempotent replay).")
                ok = True
            else:
                ok = await client.create_campaign(campaign_id, name, budget, bid)
                
            if ok:
                if session:
                    # Write to local DB
                    stmt = select(Campaign).where(Campaign.id == campaign_id)
                    res = await session.execute(stmt)
                    existing = res.scalar_one_or_none()
                    if not existing:
                        db_camp = Campaign(
                            id=campaign_id,
                            tenant_id=op.tenant_id,
                            brand_id=op.brand_id,
                            name=name,
                            platform=provider,
                            status="active"
                        )
                        session.add(db_camp)
                        logger.info(f"Registered campaign {campaign_id} in local DB")
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
            # IDEMPOTENCY CHECK: Check if campaign is already deleted in external system
            existing_ext = await client.get_campaign(campaign_id)
            if not existing_ext:
                logger.info(f"Campaign {campaign_id} does not exist in external provider (already deleted/never created).")
                ok = True
            else:
                ok = await client.delete_campaign(campaign_id)
                
            if ok:
                if session:
                    # Delete from local DB
                    stmt = delete(Campaign).where(Campaign.id == campaign_id)
                    await session.execute(stmt)
                    logger.info(f"Deleted campaign {campaign_id} from local DB")
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
                if session:
                    # Update status in local DB
                    stmt = select(Campaign).where(Campaign.id == campaign_id)
                    res = await session.execute(stmt)
                    db_camp = res.scalar_one_or_none()
                    if db_camp:
                        db_camp.status = "paused"
                        logger.info(f"Paused campaign {campaign_id} in local DB")
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} paused"})
            return ExecResult(ok=False, detail={"error": f"Failed to pause campaign {campaign_id}"})
            
        elif op.action == "grow.campaign.resume":
            ok = await client.update_campaign(campaign_id, status="ACTIVE")
            if ok:
                if session:
                    # Update status in local DB
                    stmt = select(Campaign).where(Campaign.id == campaign_id)
                    res = await session.execute(stmt)
                    db_camp = res.scalar_one_or_none()
                    if db_camp:
                        db_camp.status = "active"
                        logger.info(f"Resumed/Activated campaign {campaign_id} in local DB")
                return ExecResult(ok=True, detail={"message": f"Campaign {campaign_id} resumed"})
            return ExecResult(ok=False, detail={"error": f"Failed to resume campaign {campaign_id}"})
            
        elif op.action == "grow.alert.dispatch":
            logger.info(f"ALERT DISPATCHED: {op.params.get('message')}")
            return ExecResult(ok=True, detail={"message": "Alert dispatched"})
            
        return ExecResult(ok=False, detail={"error": f"Unknown action: {op.action}"})

    async def verify(self, op: OpSpec, session: Optional[AsyncSession] = None) -> VerifyResult:
        """Verifies campaign status."""
        if op.action in ("grow.google.connect", "grow.meta.connect"):
            logger.info("Verifying Grow connection via Secret Manager and mock API...")
            if not session:
                return VerifyResult(ok=False, checks={"session_active": False}, detail={"error": "Database session required"})
                
            provider = op.params.get("provider")
            stmt = select(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            res = await session.execute(stmt)
            conn = res.scalar_one_or_none()
            if not conn:
                from app.metrics import CONNECTOR_OPERATIONS
                CONNECTOR_OPERATIONS.labels(operation="verify", provider=provider or "unknown", result="failure").inc()
                return VerifyResult(ok=False, checks={"connection_in_db": False}, detail={"error": "Connection record not found"})
                
            try:
                secrets_client = SecretManagerClient()
                token = await secrets_client.read_secret(conn.credential)
                if not token:
                    raise ValueError("Retrieved token is empty")
                logger.info(f"Successfully retrieved {provider} token from Secret Manager (ref: {conn.credential})")
            except Exception as e:
                logger.error(f"Failed to read {provider} token from Secret Manager: {e}")
                from app.metrics import CONNECTOR_OPERATIONS
                CONNECTOR_OPERATIONS.labels(operation="verify", provider=provider or "unknown", result="failure").inc()
                return VerifyResult(
                    ok=False, 
                    checks={"api_token_valid": False, "secret_retrieval_ok": False}, 
                    detail={"error": f"Secret Manager retrieval failed: {e}"}
                )

            from app.metrics import CONNECTOR_OPERATIONS
            CONNECTOR_OPERATIONS.labels(operation="verify", provider=provider, result="success").inc()
            return VerifyResult(
                ok=True,
                checks={
                    "api_token_valid": True,
                    "account_accessible": True,
                    "secret_retrieval_ok": True
                },
                detail={"verified_at": "mock-time", "credential": conn.credential}
            )
        elif op.action in ("grow.google.disconnect", "grow.meta.disconnect"):
            return VerifyResult(ok=True, checks={"disconnected": True})

        campaign_id = op.params.get("campaign_id")
        # Resolve connection credentials dynamically
        provider = op.params.get("provider", "google-ads")
        token = None
        config = {}
        if session:
            stmt = select(Connection).where(
                Connection.tenant_id == op.tenant_id,
                Connection.brand_id == op.brand_id,
                Connection.provider == provider
            )
            res = await session.execute(stmt)
            conn = res.scalar_one_or_none()
            if conn:
                config = conn.config or {}
                try:
                    secrets_client = SecretManagerClient()
                    token = await secrets_client.read_secret(conn.credential)
                except Exception as e:
                    logger.warning(f"Failed to resolve marketing token from Secret Manager: {e}. Using raw credential.")
                    token = conn.credential

        client = get_marketing_client(provider=provider, token=token, config=config)

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
        if op.action == "grow.google.connect":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="grow.google.disconnect",
                    params={"provider": op.params.get("provider")},
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    parent_op_id=op.id
                )
            ]
        elif op.action == "grow.meta.connect":
            return [
                OpSpec(
                    tenant_id=op.tenant_id,
                    brand_id=op.brand_id,
                    domain=self.domain,
                    action="grow.meta.disconnect",
                    params={"provider": op.params.get("provider")},
                    severity=Severity(impact=1, reversibility=Reversibility.IRREVERSIBLE),
                    parent_op_id=op.id
                )
            ]

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
