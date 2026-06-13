import logging
import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, get_worker_db, get_worker_session_maker
from app.tasks import enqueue_drain
from app.middleware import TenantIsolationMiddleware, TraceMiddleware
from app.observability import setup_logging
from app.whatsapp import send_whatsapp_card_task, process_whatsapp_webhook_payload
from app.adapters.provision import ProvisionAdapter
from app.adapters.presence import PresenceAdapter
from app.adapters.grow import GrowAdapter
from app.adapters.manage import ManageAdapter
from app.adapters.build import BuildAdapter
from .kernel import loop
from .kernel.services import audit_verify, approval_latency_rollup
from .models import Brand, OpRow, OpTrace, Tenant, TrustSnapshot, Cadence, Order, Connection

# Setup Sentry SDK if DSN is set
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO")
json_format = os.getenv("LOG_FORMAT", "text").lower() == "json"
setup_logging(level=log_level, json_format=json_format)

loop.register(ProvisionAdapter())
loop.register(PresenceAdapter())
loop.register(GrowAdapter())
loop.register(ManageAdapter())
loop.register(BuildAdapter())

logger = logging.getLogger(__name__)
RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../recipes"))
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")

if os.getenv("ENV") == "production" and not WHATSAPP_APP_SECRET:
    raise RuntimeError("PRODUCTION BOOT ERROR: WHATSAPP_APP_SECRET must be set in production mode!")

app = FastAPI(title="Agency OS control plane", version="0.1.0")
app.add_middleware(TraceMiddleware)
app.add_middleware(TenantIsolationMiddleware)


def tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(401, "X-Tenant-Id header required")
    return x_tenant_id


class TenantIn(BaseModel):
    name: str
    brand_name: str


@app.post("/tenants")
async def create_tenant(body: TenantIn, s: AsyncSession = Depends(get_db)):
    t = Tenant(name=body.name)
    s.add(t)
    await s.flush()
    b = Brand(tenant_id=t.id, name=body.brand_name)
    s.add(b)
    await s.flush()
    return {"tenant_id": t.id, "brand_id": b.id}


class IntentIn(BaseModel):
    brand_id: str
    text: str
    domain: str = "provision"


@app.post("/intents")
async def submit_intent(body: IntentIn, background_tasks: BackgroundTasks,
                        s: AsyncSession = Depends(get_db),
                        worker_session_maker = Depends(get_worker_session_maker),
                        tid: str = Depends(tenant_id)):
    adapter = loop.REGISTRY.get(body.domain)
    if not adapter:
        raise HTTPException(400, f"no adapter for domain {body.domain!r}")
    
    # Derive tier from the latest TrustSnapshot for this brand and domain
    stmt = (
        select(TrustSnapshot.tier)
        .where(
            TrustSnapshot.tenant_id == tid,
            TrustSnapshot.brand_id == body.brand_id,
            TrustSnapshot.domain == body.domain
        )
        .order_by(TrustSnapshot.ts.desc())
        .limit(1)
    )
    res = await s.execute(stmt)
    tier = res.scalar_one_or_none()
    if tier is None:
        tier = 1  # Default to Supervised (Tier 1)

    cards = []
    for spec in adapter.plan(body.text, tid, body.brand_id):
        row = await loop.propose(s, spec, actor="chat")
        
        # Record LLM planning cost (simulated gemini tokens)
        from app.kernel.services import emit_cost
        await emit_cost(
            s,
            tenant_id=tid,
            op_id=row.id,
            kind="llm_tokens",
            amount_minor=57,
            currency="INR",
            meta={"model": "gemini-1.5-pro", "prompt_tokens": 450, "completion_tokens": 120},
            actor="chat"
        )

        gate, requirement = await loop.preview_and_gate(s, row, tier=tier)
        
        # Only return card / send notification for parent-less (top-level) Ops
        if row.parent_op_id is None:
            cards.append({
                "op_id": row.id, "action": row.action, "state": row.state,
                "requirement": requirement,
                "preview": row.preview_summary,
                "cost_estimate": (f"{row.cost_amount_minor/100:.2f} {row.cost_currency}/mo"
                                  if row.cost_amount_minor else None),
                "violations": [v.as_dict() for v in gate.violations],
            })
            if row.state == "AWAITING_APPROVAL":
                background_tasks.add_task(send_whatsapp_card_task, row.id, worker_session_maker)
    await s.commit()
    return {"cards": cards}


class DecisionIn(BaseModel):
    decision: str  # approve | reject
    actor: str
    role: str = "AGENCY_OWNER"
    surface: str = "web"
    reason: str | None = None


@app.post("/ops/{op_id}/decision")
async def decide(op_id: str, body: DecisionIn, background_tasks: BackgroundTasks,
                 s: AsyncSession = Depends(get_db),
                 worker_session_maker = Depends(get_worker_session_maker),
                 tid: str = Depends(tenant_id)):
    row = await s.get(OpRow, op_id)
    if not row or row.tenant_id != tid:
        raise HTTPException(404, "op not found for tenant")
    await loop.decide(s, row, decision=body.decision, actor=body.actor, role=body.role,
                surface=body.surface, reason=body.reason)
    await s.commit()
    enqueue_drain(background_tasks, worker_session_maker)
    return {"op_id": row.id, "state": row.state}


@app.get("/ops/{op_id}")
async def get_op(op_id: str, s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    row = await s.get(OpRow, op_id)
    if not row or row.tenant_id != tid:
        raise HTTPException(404, "op not found for tenant")
    result = await s.execute(select(OpTrace).filter_by(op_id=op_id).order_by(OpTrace.id))
    traces = [
        {"ts": t.ts.isoformat(), "kind": t.kind, "detail": t.detail}
        for t in result.scalars()
    ]
    return {"op_id": row.id, "action": row.action, "state": row.state, "params": row.params,
            "preview": row.preview_summary, "trace": traces}


@app.get("/audit/verify")
async def verify_audit(s: AsyncSession = Depends(get_db)):
    ok, first_bad = await audit_verify(s)
    return {"ok": ok, "first_bad_id": first_bad}


@app.get("/metrics/approval-latency")
async def approval_latency(domain: str | None = None, window_days: int | None = None,
                           s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    """North-star metric (§1): median/p90 approval latency, tenant-scoped. Read-only."""
    import datetime as _dt
    since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=window_days)
             if window_days else None)
    rollup = await approval_latency_rollup(s, tid, domain=domain, since=since)
    return {"tenant_id": tid, "domain": domain, "window_days": window_days, **rollup}


class RecipePromoteIn(BaseModel):
    recipe_name: str
    version: str = "0.1.0"


@app.post("/recipes/promote")
async def promote_recipe(body: RecipePromoteIn):
    """Promotes an experimental recipe to the production catalog and commits it to version control."""
    import shutil
    import subprocess

    experimental_path = os.path.join(RECIPES_ROOT, "experimental", body.recipe_name, body.version)
    production_path = os.path.join(RECIPES_ROOT, body.recipe_name, body.version)

    if not os.path.exists(experimental_path):
        raise HTTPException(404, f"experimental recipe {body.recipe_name} v{body.version} not found")

    required_files = ["recipe.yaml", "main.tf"]
    for rf in required_files:
        if not os.path.exists(os.path.join(experimental_path, rf)):
            raise HTTPException(400, f"missing required file {rf} in experimental recipe")

    os.makedirs(os.path.dirname(production_path), exist_ok=True)

    if os.path.exists(production_path):
         shutil.rmtree(production_path)
    shutil.copytree(experimental_path, production_path)

    try:
        repo_dir = os.path.abspath(os.path.join(RECIPES_ROOT, ".."))
        subprocess.run(["git", "add", f"recipes/{body.recipe_name}/{body.version}/"], cwd=repo_dir, check=True, capture_output=True)
        commit_res = subprocess.run(
            ["git", "commit", "-m", f"prod(catalog): promote {body.recipe_name} {body.version} to production", "-m", "TAG=agy"],
            cwd=repo_dir, check=True, capture_output=True
        )
        commit_stdout = commit_res.stdout.decode()
    except Exception as e:
        commit_stdout = f"Git commit skipped or failed: {e}"

    return {
        "status": "promoted",
        "recipe_name": body.recipe_name,
        "version": body.version,
        "catalog_path": f"recipes/{body.recipe_name}/{body.version}",
        "commit": commit_stdout
    }


WORKER_SA = os.getenv("AOS_WORKER_SERVICE_ACCOUNT")
AOS_ENV = os.getenv("AOS_ENV", "development")

async def verify_worker_auth(request: Request, authorization: str | None = Header(default=None)):
    if AOS_ENV == "test" or not WORKER_SA:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = authorization[7:]
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        google_request = google_requests.Request()
        aud_base = f"{request.url.scheme}://{request.url.netloc}{request.url.path}"
        info = id_token.verify_oauth2_token(token, google_request, audience=aud_base)

        if info.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError("Wrong issuer")

        email = info.get("email")
        if email != WORKER_SA:
            raise ValueError(f"Unauthorized service account: {email}")

    except Exception as e:
        logger.error(f"OIDC token verification failed: {e}")
        raise HTTPException(401, f"Unauthorized: {e}")


@app.post("/tasks/drain-outbox", dependencies=[Depends(verify_worker_auth)])
async def drain_outbox_task(s: AsyncSession = Depends(get_worker_db)):
    """Background task endpoint to drain the outbox.

    Bypasses RLS by using get_worker_db.
    """
    processed = await loop.drain_once(s)
    return {"status": "ok", "processed_items": processed}


@app.post("/tasks/process-cadences", dependencies=[Depends(verify_worker_auth)])
async def process_cadences(s: AsyncSession = Depends(get_worker_db)):
    """Periodic task to scan and propose recurring audit Ops from Cadences.

    Bypasses RLS by using get_worker_db to execute across all tenants.
    """
    import datetime as dt
    from app.kernel import loop
    from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

    now = dt.datetime.now(dt.timezone.utc)

    # Query due cadences
    stmt = select(Cadence).where(Cadence.next_run <= now, Cadence.status.in_(["on_track", "due", "active"]))
    res = await s.execute(stmt)
    due_cadences = res.scalars().all()

    proposed_ops_count = 0
    for cadence in due_cadences:
        # Determine schedule delta
        if cadence.schedule == "daily":
            delta = dt.timedelta(days=1)
        elif cadence.schedule == "weekly":
            delta = dt.timedelta(days=7)
        elif cadence.schedule == "monthly":
            delta = dt.timedelta(days=30)
        else:
            logger.error(f"Unknown schedule type: {cadence.schedule} for cadence {cadence.id}")
            continue

        # Compile OpSpec
        op_spec = OpSpec(
            tenant_id=cadence.tenant_id,
            brand_id=cadence.brand_id,
            domain=cadence.domain,
            action=cadence.action,
            params={"brand_id": cadence.brand_id, "cadence_id": cadence.id},
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
            cost_estimate=Money(0)
        )

        # Propose in DB
        row = await loop.propose(s, op_spec, actor="scheduler")

        # Fetch brand trust score to determine current tier
        stmt_tier = (
            select(TrustSnapshot.tier)
            .where(
                TrustSnapshot.tenant_id == cadence.tenant_id,
                TrustSnapshot.brand_id == cadence.brand_id,
                TrustSnapshot.domain == cadence.domain
            )
            .order_by(TrustSnapshot.ts.desc())
            .limit(1)
        )
        q_tier = await s.execute(stmt_tier)
        tier = q_tier.scalar()
        if tier is None:
            tier = 1

        await loop.preview_and_gate(s, row, tier=tier)
        # Update Cadence scheduling fields
        cadence.last_run = now
        cadence.next_run = now + delta
        cadence.status = "on_track"

        proposed_ops_count += 1

    await s.commit()
    return {"status": "ok", "proposed_ops_count": proposed_ops_count}


@app.post("/tasks/trust-snapshots", dependencies=[Depends(verify_worker_auth)])
async def run_trust_snapshots(s: AsyncSession = Depends(get_worker_db)):
    """Nightly job to calculate and persist trust snapshots for all brands.

    Bypasses RLS by using get_worker_db to execute across all tenants.
    """
    from .kernel.services import compute_snapshots
    await compute_snapshots(s)
    await s.commit()
    return {"status": "ok"}


@app.post("/tasks/evaluate-trust", dependencies=[Depends(verify_worker_auth)])
async def evaluate_trust(s: AsyncSession = Depends(get_worker_db)):
    """Background task evaluating campaign ROI and adjusting trust scores.

    Bypasses RLS to query across all tenants/brands.
    """
    from .models import TrustEvent
    from .kernel.services import compute_snapshots
    from app.services.marketing import MockMarketingClient
    from sqlalchemy import func
    import uuid

    # 1. Fetch all successful campaign creations
    stmt = select(OpRow).where(
        OpRow.action == "grow.campaign.create",
        OpRow.state == "DONE"
    )
    res = await s.execute(stmt)
    ops = res.scalars().all()

    client = MockMarketingClient()
    events_added = 0

    # Store performance results by platform for budget reallocation checks
    platform_performance = {}

    for op in ops:
        campaign_id = op.params.get("campaign_id")
        provider = op.params.get("provider", "google-ads")
        tenant_id = op.tenant_id
        brand_id = op.brand_id

        # Fetch platform spend
        perf = await client.get_performance(campaign_id)
        if not perf:
            continue

        spend_minor = perf.get("spend_minor", 0)
        spend_amount = spend_minor / 100.0

        # Query database orders to calculate total revenue attributed
        stmt_rev = select(func.sum(Order.amount_minor)).where(
            Order.tenant_id == tenant_id,
            Order.brand_id == brand_id,
            Order.attributed_campaign_id == campaign_id
        )
        res_rev = await s.execute(stmt_rev)
        total_revenue = (res_rev.scalar() or 0) / 100.0

        # Calculate real ROAS
        roas = total_revenue / spend_amount if spend_amount > 0 else 0.0
        logger.info(f"Campaign {campaign_id} ({provider}) - Spend: {spend_amount:.2f} INR, Database Revenue: {total_revenue:.2f} INR, ROAS: {roas:.2f}")

        # Store for reallocation comparison
        if provider not in platform_performance:
            platform_performance[provider] = {}
        platform_performance[provider][campaign_id] = {
            "roas": roas,
            "op": op,
            "budget_minor": op.params.get("budget_minor", 500_000)
        }

        # Check trust threshold logic
        kind = None
        if roas >= 1.2:
            kind = "verified_success"
            delta = 5.0
            reason = f"Campaign {campaign_id} DB ROAS {roas:.2f} >= 1.2"
        elif roas < 1.0:
            kind = "verify_failure"
            delta = -10.0
            reason = f"Campaign {campaign_id} DB ROAS {roas:.2f} < 1.0"

        if not kind:
            continue

        # Check duplicate event
        stmt_dup = select(TrustEvent).where(
            TrustEvent.tenant_id == tenant_id,
            TrustEvent.brand_id == brand_id,
            TrustEvent.domain == "grow",
            TrustEvent.kind == kind,
            TrustEvent.reason.like(f"Campaign {campaign_id}%")
        )
        res_dup = await s.execute(stmt_dup)
        dup = res_dup.scalar_one_or_none()
        if dup:
            continue

        # Record event
        event = TrustEvent(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="grow",
            kind=kind,
            base_delta=delta,
            reason=reason
        )
        s.add(event)
        events_added += 1
        logger.info(f"Recorded trust event for {brand_id}: {kind} (delta {delta})")

    # 2. Check for budget optimization/reallocation (Cross-channel)
    google_campaigns = platform_performance.get("google-ads", {})
    meta_campaigns = platform_performance.get("meta-ads", {})

    if google_campaigns and meta_campaigns:
        best_meta_id, best_meta = max(meta_campaigns.items(), key=lambda x: x[1]["roas"])
        worst_google_id, worst_google = min(google_campaigns.items(), key=lambda x: x[1]["roas"])

        transfer_amount_minor = 100_000
        if best_meta["roas"] >= 1.5 * worst_google["roas"] and worst_google["budget_minor"] > transfer_amount_minor:
            tenant_id = worst_google["op"].tenant_id
            brand_id = worst_google["op"].brand_id

            stmt_dup_saga = select(OpRow).where(
                OpRow.tenant_id == tenant_id,
                OpRow.brand_id == brand_id,
                OpRow.action == "grow.reallocate_budget.apply",
                OpRow.state == "PROPOSED"
            )
            res_dup_saga = await s.execute(stmt_dup_saga)
            if not res_dup_saga.scalar_one_or_none():
                logger.warning(f"Optimization triggered: Proposing budget reallocation from Google Ads ({worst_google_id}) to Meta Ads ({best_meta_id})")

                saga_id = uuid.uuid4().hex

                # Parent Saga
                parent_saga = OpRow(
                    id=saga_id,
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="grow",
                    action="grow.reallocate_budget.apply",
                    state="PROPOSED",
                    impact=2,
                    reversibility="COMPENSATABLE",
                    preview_summary=f"Budget Transfer: Move 1,000.00 INR from Google Ads ({worst_google['op'].params.get('name')}) to Meta Ads ({best_meta['op'].params.get('name')}) due to ROAS performance difference (Meta: {best_meta['roas']:.2f}, Google: {worst_google['roas']:.2f}).",
                    params={
                        "transfer_amount_minor": transfer_amount_minor,
                        "source_campaign_id": worst_google_id,
                        "source_provider": "google-ads",
                        "target_campaign_id": best_meta_id,
                        "target_provider": "meta-ads"
                    },
                    idem_key=f"idem_saga_{saga_id}"
                )
                s.add(parent_saga)

                # Child 1: Decrease Google Ads campaign budget
                child1_id = uuid.uuid4().hex
                child1 = OpRow(
                    id=child1_id,
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="grow",
                    action="grow.campaign.update",
                    state="PROPOSED",
                    impact=2,
                    reversibility="COMPENSATABLE",
                    params={
                        "campaign_id": worst_google_id,
                        "provider": "google-ads",
                        "budget_minor": worst_google["budget_minor"] - transfer_amount_minor,
                        "previous_budget_minor": worst_google["budget_minor"],
                        "bid_minor": worst_google["op"].params.get("bid_minor")
                    },
                    parent_op_id=saga_id,
                    sequence_order=1,
                    idem_key=f"idem_child1_{child1_id}"
                )
                s.add(child1)

                # Child 2: Increase Meta Ads campaign budget
                child2_id = uuid.uuid4().hex
                child2 = OpRow(
                    id=child2_id,
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="grow",
                    action="grow.campaign.update",
                    state="PROPOSED",
                    impact=2,
                    reversibility="COMPENSATABLE",
                    params={
                        "campaign_id": best_meta_id,
                        "provider": "meta-ads",
                        "budget_minor": best_meta["budget_minor"] + transfer_amount_minor,
                        "previous_budget_minor": best_meta["budget_minor"],
                        "bid_minor": best_meta["op"].params.get("bid_minor")
                    },
                    parent_op_id=saga_id,
                    sequence_order=2,
                    idem_key=f"idem_child2_{child2_id}"
                )
                s.add(child2)

                logger.info("Inserted budget reallocation proposed Saga Op with 2 children")

                await s.flush()

                # Run preview and gate to transition parent and children to AWAITING_APPROVAL
                await loop.preview_and_gate(s, parent_saga, tier=1)
                await loop.preview_and_gate(s, child1, tier=1)
                await loop.preview_and_gate(s, child2, tier=1)

    if events_added > 0:
        await s.flush()
        await compute_snapshots(s)

    await s.commit()
    return {"status": "ok", "events_added": events_added}


def verify_whatsapp_signature(payload: bytes, signature: str) -> bool:
    """Verifies SHA256 signature using HMAC and Meta app secret."""
    if not WHATSAPP_APP_SECRET:
        logger.warning("WHATSAPP_APP_SECRET not configured. Signature check bypassed.")
        return True
    import hmac
    import hashlib
    if signature.startswith("sha256="):
        signature = signature[7:]
    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/webhooks/whatsapp")
async def verify_whatsapp(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Webhook verification endpoint for Meta WhatsApp Cloud API."""
    import hmac
    if (hub_mode == "subscribe" and hub_verify_token and WHATSAPP_VERIFY_TOKEN
            and hmac.compare_digest(hub_verify_token, WHATSAPP_VERIFY_TOKEN)):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    worker_session_maker = Depends(get_worker_session_maker)
):
    """Webhook event receiver endpoint for Meta WhatsApp Cloud API."""
    raw_body = await request.body()

    # Verify signature if secret is configured
    if WHATSAPP_APP_SECRET:
        if not x_hub_signature_256:
            logger.warning("Rejecting WhatsApp webhook: Missing X-Hub-Signature-256 header")
            raise HTTPException(401, "Signature missing")

        if not verify_whatsapp_signature(raw_body, x_hub_signature_256):
            logger.warning("Rejecting WhatsApp webhook: Signature mismatch")
            raise HTTPException(401, "Invalid signature")

    import json
    body = json.loads(raw_body)
    logger.info(f"WhatsApp webhook received: {body}")

    # Simple validation that it is a whatsapp event
    if body.get("object") != "whatsapp_business_account":
        raise HTTPException(400, "Invalid object type")

    background_tasks.add_task(process_whatsapp_webhook_payload, body, worker_session_maker)
    return {"status": "accepted"}


@app.get("/brands/{brand_id}/status")
async def get_brand_status(brand_id: str, s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    """Fetches Shopify connection status and metrics for a brand."""
    brand = await s.get(Brand, brand_id)
    if not brand or brand.tenant_id != tid:
        raise HTTPException(404, "Brand not found")

    stmt = select(Connection).where(
        Connection.tenant_id == tid,
        Connection.brand_id == brand_id,
        Connection.provider == "shopify"
    )
    res = await s.execute(stmt)
    conn = res.scalar_one_or_none()
    if not conn:
        return {
            "brand_id": brand_id,
            "shopify_connected": False,
            "metrics": {}
        }

    # Mock token retrieval from Secret Manager
    mock_token = f"mocked-token-for-{conn.secret_ref}"

    from app.services.shopify import MockShopifyClient
    client = MockShopifyClient(shop_url=conn.config.get("shop_url"), token=mock_token)
    metrics = await client.get_metrics()

    return {
        "brand_id": brand_id,
        "shopify_connected": True,
        "metrics": metrics
    }

