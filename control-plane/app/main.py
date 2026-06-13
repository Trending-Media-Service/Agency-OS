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
from .kernel import loop
from .kernel.services import audit_verify
from .models import Brand, OpRow, OpTrace, Tenant, TrustSnapshot, Cadence

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

logger = logging.getLogger(__name__)
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
            meta={"model": "gemini-1.5-pro", "prompt_tokens": 450, "completion_tokens": 120}
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


@app.post("/tasks/drain-outbox")
async def drain_outbox_task(s: AsyncSession = Depends(get_worker_db)):
    """Background task endpoint to drain the outbox.

    Bypasses RLS by using get_worker_db.
    """
    processed = await loop.drain_once(s)
    return {"status": "ok", "processed_items": processed}


@app.post("/tasks/process-cadences")
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


@app.post("/tasks/trust-snapshots")
async def run_trust_snapshots(s: AsyncSession = Depends(get_worker_db)):
    """Nightly job to calculate and persist trust snapshots for all brands.

    Bypasses RLS by using get_worker_db to execute across all tenants.
    """
    from .kernel.services import compute_snapshots
    await compute_snapshots(s)
    await s.commit()
    return {"status": "ok"}


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

