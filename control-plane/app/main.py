import logging
import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, get_worker_db, get_worker_session_maker
from app.tasks import enqueue_drain
from app.middleware import TenantIsolationMiddleware
from app.whatsapp import send_whatsapp_card_task, process_whatsapp_webhook_payload
from app.adapters.provision import ProvisionAdapter
from .kernel import loop
from .kernel.services import audit_verify
from .models import Brand, OpRow, OpTrace, Tenant, TrustSnapshot

loop.register(ProvisionAdapter())

logger = logging.getLogger(__name__)
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

app = FastAPI(title="Agency OS control plane", version="0.1.0")
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
        gate, requirement = await loop.preview_and_gate(s, row, tier=tier)
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
    return {"op_id": row.id, "action": row.action, "state": row.state,
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


@app.post("/tasks/trust-snapshots")
async def run_trust_snapshots(s: AsyncSession = Depends(get_worker_db)):
    """Nightly job to calculate and persist trust snapshots for all brands.

    Bypasses RLS by using get_worker_db to execute across all tenants.
    """
    from .kernel.services import compute_snapshots
    await compute_snapshots(s)
    await s.commit()
    return {"status": "ok"}


@app.get("/webhooks/whatsapp")
async def verify_whatsapp(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Webhook verification endpoint for Meta WhatsApp Cloud API."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(403, "Verification failed")


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    worker_session_maker = Depends(get_worker_session_maker)
):
    """Webhook event receiver endpoint for Meta WhatsApp Cloud API."""
    body = await request.json()
    logger.info(f"WhatsApp webhook received: {body}")

    # Simple validation that it is a whatsapp event
    if body.get("object") != "whatsapp_business_account":
        raise HTTPException(400, "Invalid object type")

    background_tasks.add_task(process_whatsapp_webhook_payload, body, worker_session_maker)
    return {"status": "accepted"}

