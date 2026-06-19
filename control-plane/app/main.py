import logging
import os
import datetime as dt

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.database import get_db, get_worker_db, get_worker_session_maker, tenant_context
from app.tasks import enqueue_drain
from app.middleware import TenantIsolationMiddleware, TraceMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, MetricsMiddleware
from app.observability import setup_logging
from app.whatsapp import send_whatsapp_card_task, process_whatsapp_webhook_payload
from app.adapters.provision import ProvisionAdapter
from app.adapters.presence import PresenceAdapter
from app.adapters.grow import GrowAdapter
from app.adapters.manage import ManageAdapter
from app.adapters.build import BuildAdapter
from app.adapters.governance import GovernanceAdapter
from app.adapters.dr import DRAdapter
from .kernel import loop
from .kernel.services import audit_verify, approval_latency_rollup
from .kernel.plugins import register_plugin, get_plugin, ShopifyPlugin
from .models import Brand, OpRow, OpTrace, Tenant, TrustSnapshot, Cadence, Order, Connection, CircuitBreakerRow, AuditEvent

# Setup Sentry SDK if DSN is set
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration
    
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            HttpxIntegration(),
        ],
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
loop.register(GovernanceAdapter())
loop.register(DRAdapter())

register_plugin(ShopifyPlugin())


logger = logging.getLogger(__name__)
RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../recipes"))
logger.info(f"RECIPES_ROOT resolved to: {RECIPES_ROOT}")
try:
    if os.path.exists(RECIPES_ROOT):
        logger.info(f"Contents of RECIPES_ROOT: {os.listdir(RECIPES_ROOT)}")
    else:
        logger.warning(f"RECIPES_ROOT does not exist!")
except Exception as e:
    logger.error(f"Failed to list RECIPES_ROOT: {e}")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")

if os.getenv("ENV") == "production" and not WHATSAPP_APP_SECRET:
    raise RuntimeError("PRODUCTION BOOT ERROR: WHATSAPP_APP_SECRET must be set in production mode!")

logger = logging.getLogger(__name__)
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

app = FastAPI(title="Agency OS control plane", version="0.1.0")


# The operator/brand console (control-plane/web) is served from a separate
# Cloud Run origin, so browser calls to this API are cross-origin. Origins come
# from ALLOWED_ORIGINS (comma-separated); localhost + the deployed console URL
# are the defaults so the console works out of the box.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,https://agency-os-web-730671240713.asia-south1.run.app",
    ).split(",")
    if o.strip()
]


def _cors_headers_for(request: Request) -> dict[str, str]:
    """CORS headers for a manually-built error response.

    Unhandled 500s are produced by Starlette's ServerErrorMiddleware, which sits
    OUTSIDE CORSMiddleware — so without this the browser sees a header-less error
    and reports an opaque "Failed to fetch" instead of the real status/detail.
    """
    origin = request.headers.get("origin")
    if origin and origin in ALLOWED_ORIGINS:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from app.observability import trace_context
    trace_id = trace_context.get("unknown")
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "trace_id": trace_id},
        headers=_cors_headers_for(request),
    )

app.add_middleware(TraceMiddleware)
app.add_middleware(TenantIsolationMiddleware)
app.add_middleware(RateLimitMiddleware, rate=0.2, capacity=5.0)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MetricsMiddleware)
# Added LAST so it is the OUTERMOST middleware: CORSMiddleware answers the
# preflight OPTIONS itself, before TenantIsolationMiddleware (which would 400 a
# preflight that carries no X-Tenant-ID header).
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)
OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "default-dev-token")
if os.getenv("ENV") == "production" and OPERATOR_TOKEN == "default-dev-token":
    raise RuntimeError("PRODUCTION BOOT ERROR: OPERATOR_TOKEN must be explicitly set — default is forbidden")

async def verify_operator_auth(authorization: str | None = Header(default=None)):
    """Verifies that the request carries a valid Operator Bearer Token in the Authorization header."""
    import hmac
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:]
    if not hmac.compare_digest(token, OPERATOR_TOKEN):
        raise HTTPException(403, "Forbidden: Invalid operator token")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(s: AsyncSession = Depends(get_db)):
    try:
        await s.execute(select(1))
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "error": str(e)}
        )


@app.get("/metrics")
async def metrics_endpoint():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)



def tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(401, "X-Tenant-Id header required")
    return x_tenant_id


class TenantIn(BaseModel):
    name: str = Field(max_length=200)
    brand_name: str = Field(max_length=200)


class OpOut(BaseModel):
    op_id: str
    tenant_id: str
    brand_id: str
    domain: str
    action: str
    state: str
    preview: str | None = None
    cost_estimate: str | None = None


class ConnectionOut(BaseModel):
    id: str
    provider: str
    scope: str
    secret_ref: str
    config: dict
    created_at: dt.datetime


class CircuitBreakerOut(BaseModel):
    brand_id: str
    domain: str
    state: str
    consecutive_failures: int
    tripped_at: dt.datetime | None = None
    last_failure_at: dt.datetime | None = None


class AuditEventOut(BaseModel):
    id: int
    ts: dt.datetime
    actor: str
    action: str
    op_id: str | None = None
    payload: dict
    hash: str


class AuditVerifyOut(BaseModel):
    ok: bool
    first_bad_id: int | None = None


@app.post("/tenants", dependencies=[Depends(verify_operator_auth)])
async def create_tenant(body: TenantIn, s: AsyncSession = Depends(get_worker_db)):
    import uuid
    tenant_id = uuid.uuid4().hex
    # Set the tenant context so the INSERTs satisfy the RLS WITH CHECK policies on
    # tenants/brands (the worker role is RLS-enforced, not BYPASSRLS). set_config is a
    # Postgres function — guard on dialect so the SQLite test database isn't hit with it.
    if s.bind and s.bind.dialect.name == "postgresql":
        await s.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id}
        )

    t = Tenant(id=tenant_id, name=body.name)
    s.add(t)
    await s.flush()
    
    b = Brand(tenant_id=t.id, name=body.brand_name)
    s.add(b)
    await s.flush()
    
    return {"tenant_id": t.id, "brand_id": b.id}


class TenantBrandOut(BaseModel):
    tenant_id: str
    tenant_name: str
    brand_id: str
    brand_name: str


@app.get("/tenants", response_model=list[TenantBrandOut], dependencies=[Depends(verify_operator_auth)])
async def list_tenants(s: AsyncSession = Depends(get_worker_db)):
    """Lists all tenants and their brands.

    Bypasses RLS (uses get_worker_db) to allow the operator console to discover tenants.
    """
    stmt = select(
        Tenant.id.label("tenant_id"),
        Tenant.name.label("tenant_name"),
        Brand.id.label("brand_id"),
        Brand.name.label("brand_name")
    ).join(Brand, Brand.tenant_id == Tenant.id).order_by(Tenant.name, Brand.name)

    res = await s.execute(stmt)
    return [dict(row) for row in res.mappings().all()]


class ChatIn(BaseModel):
    brand_id: str = Field(max_length=100)
    text: str = Field(max_length=5000)


@app.post("/chat")
async def chat(body: ChatIn, background_tasks: BackgroundTasks,
               s: AsyncSession = Depends(get_db),
               worker_session_maker = Depends(get_worker_session_maker),
               tid: str = Depends(tenant_id)):
    """Conversational intent routing endpoint. Translates text to structured adapter intents."""
    from app.kernel.tools import registry as tool_registry, parse_chat_to_tool_call
    tool_match = parse_chat_to_tool_call(body.text)
    if tool_match:
        tool_name, args = tool_match
        tool = tool_registry.get_tool(tool_name)
        if tool:
            handler = tool["handler"]
            # Call the handler with tenant_id injected
            specs = handler(tenant_id=tid, **args)
            
            # Resolve trust tier for this domain (defaults to 1 supervised)
            domain_name = specs[0].domain
            stmt = (
                select(TrustSnapshot.tier)
                .where(
                    TrustSnapshot.tenant_id == tid,
                    TrustSnapshot.brand_id == body.brand_id,
                    TrustSnapshot.domain == domain_name
                )
                .order_by(TrustSnapshot.ts.desc())
                .limit(1)
            )
            res = await s.execute(stmt)
            tier = res.scalar_one_or_none()
            if tier is None:
                tier = 1

            cards = []
            for spec in specs:
                # Propose and gate the operation! RLS and safety gates apply unconditionally.
                row = await loop.propose(s, spec, actor="chat:tool")
                gate, requirement = await loop.preview_and_gate(s, row, tier=tier, actor="chat:tool")
                
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
            # Drain so auto-approved (within-policy) Ops actually execute — they are
            # APPROVED with a PENDING outbox item but no /decision call fires otherwise.
            enqueue_drain(background_tasks, worker_session_maker)
            return {
                "reply": f"Structured request parsed. Generated {len(cards)} proposal(s) under safety gates.",
                "cards": cards
            }

    normalized = body.text.lower()
    has_domain = any("." in w and not w.startswith(".") for w in body.text.replace(",", " ").split())

    # --- Read-only conversational intents: answer directly, propose nothing. ---
    # "check budgets" — cost-to-date for the tenant (read-only; no Op, no gate).
    if any(w in normalized for w in ["budget", "cost", "spend", "how much", "profit", "margin"]):
        from app.kernel.services import get_tenant_cost_rollup
        rollup = await get_tenant_cost_rollup(s, tid)
        if rollup:
            parts = ", ".join(f"{k}: {v / 100:.2f} INR" for k, v in rollup.items())
            total = sum(rollup.values()) / 100
            reply = f"Cost-to-date for this tenant — {parts}. Total: {total:.2f} INR."
        else:
            reply = "No costs have been recorded for this tenant yet."
        return {"reply": reply, "cards": []}

    # "trigger diagnostics" — audit-chain integrity + circuit-breaker status (read-only).
    if any(w in normalized for w in ["diagnostic", "status", "health", "audit", "integrity", "breaker"]):
        ok, first_bad = await audit_verify(s)
        br = (await s.execute(select(CircuitBreakerRow).where(CircuitBreakerRow.tenant_id == tid))).scalars().all()
        tripped = [b.domain for b in br if (b.state or "").upper() == "OPEN"]
        audit_line = "audit chain intact" if ok else f"AUDIT CHAIN BROKEN at block {first_bad}"
        br_line = (f"{len(tripped)} circuit breaker(s) tripped ({', '.join(tripped)})"
                   if tripped else "all circuit breakers healthy")
        return {"reply": f"Diagnostics — {audit_line}; {br_line}.", "cards": []}

    # --- Provisioning intents: route to the governed loop (propose -> gate). ---
    if "static" in normalized:
        words = body.text.replace(",", " ").split()
        domain = next((w for w in words if "." in w and not w.startswith(".")), "example.in")
        intent_text = f"static website hosting for {domain}"
        domain_name = "provision"
    elif any(w in normalized for w in ["email", "dns", "mx", "spf", "dkim"]):
        words = body.text.replace(",", " ").split()
        domain = next((w for w in words if "." in w and not w.startswith(".")), "example.in")
        intent_text = f"configure email dns routing for domain {domain}"
        domain_name = "provision"
    elif any(w in normalized for w in ["bootstrap", "onboard", "host", "provision", "deploy", "website", "launch"]) or has_domain:
        intent_text = body.text
        domain_name = "provision"
    else:
        # Unrecognized — guide the operator instead of silently proposing a deploy.
        return {
            "reply": (
                "I didn't recognize that as an action. I can: host a site "
                "(e.g. \"host ableys.in\"), pause a campaign (\"pause campaign camp-1\"), "
                "adjust a bid (\"adjust bid for campaign camp-1 to 50 inr\"), "
                "check budgets (\"what's my spend?\"), or run diagnostics (\"show system status\")."
            ),
            "cards": [],
        }

    adapter = loop.REGISTRY.get(domain_name)
    if not adapter:
        raise HTTPException(400, f"no adapter for domain {domain_name!r}")

    # Derive tier from the latest TrustSnapshot for this brand and domain
    stmt = (
        select(TrustSnapshot.tier)
        .where(
            TrustSnapshot.tenant_id == tid,
            TrustSnapshot.brand_id == body.brand_id,
            TrustSnapshot.domain == domain_name
        )
        .order_by(TrustSnapshot.ts.desc())
        .limit(1)
    )
    res = await s.execute(stmt)
    tier = res.scalar_one_or_none()
    if tier is None:
        tier = 1

    cards = []
    for spec in adapter.plan(intent_text, tid, body.brand_id):
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
    # Drain so auto-approved (within-policy) Ops actually execute — they are APPROVED
    # with a PENDING outbox item but no /decision call fires otherwise.
    enqueue_drain(background_tasks, worker_session_maker)
    return {
        "reply": f"Understood. I have initiated the planning for your request: '{intent_text}'. Please approve the generated proposal.",
        "cards": cards
    }


class IntentIn(BaseModel):
    brand_id: str = Field(max_length=100)
    text: str = Field(max_length=5000)
    domain: str = Field(default="provision", max_length=50)


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
            if row.state in ("AWAITING_APPROVAL", "BLOCKED"):
                background_tasks.add_task(send_whatsapp_card_task, row.id, worker_session_maker)
    await s.commit()
    # Auto-approved (within-policy) Ops are now APPROVED with a PENDING outbox item
    # (loop.preview_and_gate -> enqueue), but nothing has triggered execution. Drain
    # the outbox so they actually run — mirrors POST /ops/{op_id}/decision. drain_once
    # only processes PENDING items, so this is a no-op when every Op awaits approval.
    enqueue_drain(background_tasks, worker_session_maker)
    return {"cards": cards}


class ActionIn(BaseModel):
    tool: str = Field(max_length=100)
    brand_id: str = Field(max_length=100)
    params: dict = Field(default_factory=dict)


@app.get("/actions/catalog")
async def actions_catalog(tid: str = Depends(tenant_id)):
    """Tool schemas backing the console's explicit Action Panel (replaces the chat)."""
    from app.kernel.tools import registry as tool_registry
    return {"actions": tool_registry.get_schemas()}


@app.post("/actions")
async def submit_action(body: ActionIn, background_tasks: BackgroundTasks,
                        s: AsyncSession = Depends(get_db),
                        worker_session_maker = Depends(get_worker_session_maker),
                        tid: str = Depends(tenant_id)):
    """Structured operator action -> governed Op(s). No free-text parsing: routes the
    chosen tool + params through the tool registry, then propose -> preview_and_gate ->
    drain. Gates and approval are unchanged (auto-approve within policy, else the Op
    waits in the queue / WhatsApp)."""
    from app.kernel.tools import registry as tool_registry
    tool = tool_registry.get_tool(body.tool)
    if not tool:
        raise HTTPException(400, f"unknown action {body.tool!r}")
    if "brand_id" in body.params or "tenant_id" in body.params:
        raise HTTPException(400, "brand_id/tenant_id are supplied by the request, not in params")
    try:
        specs = tool["handler"](tenant_id=tid, brand_id=body.brand_id, **body.params)
    except TypeError as e:
        raise HTTPException(400, f"invalid params for action {body.tool!r}: {e}")

    cards = []
    for spec in specs:
        # Derive tier from the latest TrustSnapshot for this brand+domain (default 1).
        stmt = (
            select(TrustSnapshot.tier)
            .where(
                TrustSnapshot.tenant_id == tid,
                TrustSnapshot.brand_id == body.brand_id,
                TrustSnapshot.domain == spec.domain,
            )
            .order_by(TrustSnapshot.ts.desc())
            .limit(1)
        )
        t = (await s.execute(stmt)).scalar_one_or_none()
        tier = 1 if t is None else t

        row = await loop.propose(s, spec, actor="forms:operator")
        gate, requirement = await loop.preview_and_gate(s, row, tier=tier)
        if row.parent_op_id is None:
            cards.append({
                "op_id": row.id, "action": row.action, "state": row.state,
                "requirement": requirement,
                "preview": row.preview_summary,
                "cost_estimate": (f"{row.cost_amount_minor/100:.2f} {row.cost_currency}/mo"
                                  if row.cost_amount_minor else None),
                "violations": [v.as_dict() for v in gate.violations],
            })
            if row.state in ("AWAITING_APPROVAL", "BLOCKED"):
                background_tasks.add_task(send_whatsapp_card_task, row.id, worker_session_maker)
    await s.commit()
    # Execute auto-approved Ops (same governed drain path as /chat and /decision).
    enqueue_drain(background_tasks, worker_session_maker)
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
    try:
        await loop.decide(s, row, decision=body.decision, actor=body.actor, role=body.role,
                    surface=body.surface, reason=body.reason)
        await s.commit()
    except loop.RBACError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
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


@app.get("/ops", response_model=list[OpOut])
async def list_ops(
    state: str | None = None,
    domain: str | None = None,
    brand_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    s: AsyncSession = Depends(get_db),
    tid: str = Depends(tenant_id)
):
    stmt = select(OpRow).where(OpRow.tenant_id == tid)
    if state:
        stmt = stmt.where(OpRow.state == state)
    if domain:
        stmt = stmt.where(OpRow.domain == domain)
    if brand_id:
        stmt = stmt.where(OpRow.brand_id == brand_id)
        
    stmt = stmt.order_by(OpRow.id.desc()).offset(offset).limit(limit)
    res = await s.execute(stmt)
    rows = res.scalars().all()
    
    return [
        {
            "op_id": row.id,
            "tenant_id": row.tenant_id,
            "brand_id": row.brand_id,
            "domain": row.domain,
            "action": row.action,
            "state": row.state,
            "preview": row.preview_summary,
            "cost_estimate": (f"{row.cost_amount_minor/100:.2f} {row.cost_currency}/mo"
                              if row.cost_amount_minor else None),
        }
        for row in rows
    ]


@app.get("/audit/verify", response_model=AuditVerifyOut)
async def verify_audit(s: AsyncSession = Depends(get_db)):
    ok, first_bad = await audit_verify(s)
    return {"ok": ok, "first_bad_id": first_bad}


@app.get("/connections", response_model=list[ConnectionOut])
async def list_connections(s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    stmt = select(Connection).where(Connection.tenant_id == tid)
    res = await s.execute(stmt)
    conns = res.scalars().all()
    return [
        {
            "id": c.id,
            "provider": c.provider,
            "scope": c.scope,
            "secret_ref": c.secret_ref,
            "config": c.config,
            "created_at": c.created_at
        } for c in conns
    ]


@app.get("/circuit-breakers", response_model=list[CircuitBreakerOut])
async def list_circuit_breakers(s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    stmt = select(CircuitBreakerRow).where(CircuitBreakerRow.tenant_id == tid)
    res = await s.execute(stmt)
    breakers = res.scalars().all()
    return [
        {
            "brand_id": cb.brand_id,
            "domain": cb.domain,
            "state": cb.state,
            "consecutive_failures": cb.consecutive_failures,
            "tripped_at": cb.tripped_at,
            "last_failure_at": cb.last_failure_at
        } for cb in breakers
    ]


@app.get("/audit/events", response_model=list[AuditEventOut])
async def list_audit_events(limit: int = 50, s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == tid).order_by(AuditEvent.id.desc()).limit(limit)
    res = await s.execute(stmt)
    events = res.scalars().all()
    return [
        {
            "id": ev.id,
            "ts": ev.ts,
            "actor": ev.actor,
            "action": ev.action,
            "op_id": ev.op_id,
            "payload": ev.payload,
            "hash": ev.hash
        } for ev in events
    ]


@app.get("/metrics/approval-latency")
async def approval_latency(domain: str | None = None, window_days: int | None = None,
                           s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    """North-star metric (§1): median/p90 approval latency, tenant-scoped. Read-only."""
    import datetime as _dt
    since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=window_days)
             if window_days else None)
    rollup = await approval_latency_rollup(s, tid, domain=domain, since=since)
    return {"tenant_id": tid, "domain": domain, "window_days": window_days, **rollup}


@app.get("/autonomy-confidence")
async def autonomy_confidence(
    brand_id: str | None = None,
    domain: str | None = None,
    window_days: int | None = None,
    s: AsyncSession = Depends(get_db),
    tid: str = Depends(tenant_id)
):
    """Computes autonomy confidence metrics (agreement rate, critical disagreements)
    for shadow Tier-2 decisions against human Tier-1 decisions.
    """
    import datetime as _dt
    from app.models import ShadowDecision, OpRow
    
    stmt = select(ShadowDecision).join(OpRow, ShadowDecision.op_id == OpRow.id)
    stmt = stmt.where(ShadowDecision.tenant_id == tid)
    
    if brand_id:
        stmt = stmt.where(OpRow.brand_id == brand_id)
    if domain:
        stmt = stmt.where(OpRow.domain == domain)
    if window_days:
        since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=window_days)
        # SQLite stores naive datetimes; compare with naive UTC
        since = since.replace(tzinfo=None)
        stmt = stmt.where(ShadowDecision.ts >= since)
        
    res = await s.execute(stmt)
    decisions = res.scalars().all()
    
    total = len(decisions)
    if total == 0:
        return {
            "tenant_id": tid,
            "brand_id": brand_id,
            "domain": domain,
            "window_days": window_days,
            "total_decisions": 0,
            "agreement_rate": 1.0,
            "critical_disagreements": 0,
            "recommendation": "OBSERVE",
            "message": "No shadow decisions recorded in this window."
        }
        
    agreed_count = sum(1 for d in decisions if d.agreed)
    critical_count = sum(1 for d in decisions if not d.agreed and d.human_decision == "reject" and d.shadow_requirement == "AUTO")
    
    agreement_rate = agreed_count / total
    
    if total < 5:
        recommendation = "OBSERVE"
        message = f"Insufficient data ({total} decision(s)). Recommend observing further."
    elif agreement_rate >= 0.90 and critical_count == 0:
        recommendation = "PROCEED"
        message = "High agreement rate and zero critical disagreements. Autonomy promotion recommended."
    else:
        recommendation = "HOLD"
        message = "Agreement rate below 90% or critical disagreements detected. Review shadow logs."
        
    return {
        "tenant_id": tid,
        "brand_id": brand_id,
        "domain": domain,
        "window_days": window_days,
        "total_decisions": total,
        "agreement_rate": agreement_rate,
        "critical_disagreements": critical_count,
        "recommendation": recommendation,
        "message": message
    }


class PolicySimulateIn(BaseModel):
    proposed_params: dict
    window_days: int | None = 30
    max_ops: int = 500
    save_draft: bool = False
    note: str | None = None
    created_by: str | None = None


@app.post("/policy-simulate", dependencies=[Depends(verify_operator_auth)])
async def policy_simulate(
    body: PolicySimulateIn,
    s: AsyncSession = Depends(get_db),
    tid: str = Depends(tenant_id)
):
    """Replays historical operations against proposed ruleset changes and returns the differences."""
    from app.kernel.services import simulate_policy
    from app.models import PolicyVersion

    sim_res = await simulate_policy(
        s,
        tenant_id=tid,
        proposed_params_dict=body.proposed_params,
        window_days=body.window_days,
        max_ops=body.max_ops
    )

    draft_version = None
    if body.save_draft:
        # Determine next version
        stmt = (
            select(PolicyVersion.version)
            .where(PolicyVersion.tenant_id == tid)
            .order_by(PolicyVersion.version.desc())
            .limit(1)
        )
        res = await s.execute(stmt)
        last_version = res.scalar_one_or_none() or 0
        next_version = last_version + 1

        from app.kernel.services import load_active_ruleset_params
        baseline_params = await load_active_ruleset_params(s, tid)
        base_dict = baseline_params.__dict__.copy()
        base_dict.update(body.proposed_params)

        draft = PolicyVersion(
            tenant_id=tid,
            version=next_version,
            status="proposed",
            params=base_dict,
            note=body.note,
            created_by=body.created_by
        )
        s.add(draft)
        await s.commit()
        draft_version = next_version

    return {
        "simulation": sim_res,
        "draft_version": draft_version
    }


class RecipePromoteIn(BaseModel):
    recipe_name: str
    version: str = "0.1.0"


@app.post("/recipes/promote", dependencies=[Depends(verify_operator_auth)])
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


@app.post("/tasks/calibrate-attribution", dependencies=[Depends(verify_worker_auth)])
async def calibrate_attribution(s: AsyncSession = Depends(get_worker_db)):
    """Runs Meridian calibration to compute incrementality multipliers for all brands.

    Bypasses RLS by using get_worker_db.
    """
    from app.services.attribution import run_meridian_calibration
    
    stmt = select(Brand)
    res = await s.execute(stmt)
    brands = res.scalars().all()
    
    calibrated_count = 0
    for brand in brands:
        await run_meridian_calibration(s, brand.tenant_id, brand.id)
        calibrated_count += 1
        
    await s.commit()
    return {"status": "ok", "calibrated_count": calibrated_count}


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
                OpRow.action == "grow.budget.reallocate",
                OpRow.state == "PROPOSED"
            )
            res_dup_saga = await s.execute(stmt_dup_saga)
            if not res_dup_saga.scalar_one_or_none():
                logger.warning(f"Optimization triggered: Proposing budget reallocation from Google Ads ({worst_google_id}) to Meta Ads ({best_meta_id})")

                from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

                # Propose Parent Saga
                parent_saga = await loop.propose(s, OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="grow",
                    action="grow.budget.reallocate",
                    params={
                        "transfer_amount_minor": transfer_amount_minor,
                        "source_campaign_id": worst_google_id,
                        "source_provider": "google-ads",
                        "target_campaign_id": best_meta_id,
                        "target_provider": "meta-ads"
                    },
                    severity=Severity(2, Reversibility.COMPENSATABLE),
                    cost_estimate=Money(0, "INR"),
                ), actor="optimizer")

                # Propose Child 1: Decrease Google Ads campaign budget
                child1 = await loop.propose(s, OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="grow",
                    action="grow.campaign.update",
                    params={
                        "campaign_id": worst_google_id,
                        "provider": "google-ads",
                        "budget_minor": worst_google["budget_minor"] - transfer_amount_minor,
                        "previous_budget_minor": worst_google["budget_minor"],
                        "bid_minor": worst_google["op"].params.get("bid_minor")
                    },
                    severity=Severity(2, Reversibility.COMPENSATABLE),
                    cost_estimate=Money(0, "INR"),
                    parent_op_id=parent_saga.id,
                    sequence_order=1
                ), actor="optimizer")

                # Propose Child 2: Increase Meta Ads campaign budget
                child2 = await loop.propose(s, OpSpec(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    domain="grow",
                    action="grow.campaign.update",
                    params={
                        "campaign_id": best_meta_id,
                        "provider": "meta-ads",
                        "budget_minor": best_meta["budget_minor"] + transfer_amount_minor,
                        "previous_budget_minor": best_meta["budget_minor"],
                        "bid_minor": best_meta["op"].params.get("bid_minor")
                    },
                    severity=Severity(2, Reversibility.COMPENSATABLE),
                    cost_estimate=Money(0, "INR"),
                    parent_op_id=parent_saga.id,
                    sequence_order=2
                ), actor="optimizer")

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


async def resolve_whatsapp_secret() -> str | None:
    """Resolves the WhatsApp App Secret from Secret Manager if configured as a ref, or env var."""
    if not WHATSAPP_APP_SECRET:
        return None
    if WHATSAPP_APP_SECRET.startswith("projects/"):
        from app.services.secrets import SecretManagerClient
        try:
            secrets_client = SecretManagerClient()
            return await secrets_client.read_secret(WHATSAPP_APP_SECRET)
        except Exception as e:
            logger.error(f"Failed to resolve WHATSAPP_APP_SECRET from Secret Manager reference {WHATSAPP_APP_SECRET}: {e}")
            raise RuntimeError(f"Failed to resolve WhatsApp secret from Secret Manager: {e}")
    return WHATSAPP_APP_SECRET


async def verify_whatsapp_signature(payload: bytes, signature: str) -> bool:
    """Verifies SHA256 signature using HMAC and Meta app secret."""
    secret_value = await resolve_whatsapp_secret()
    if not secret_value:
        logger.warning("WHATSAPP_APP_SECRET not configured. Signature check bypassed.")
        return True
    import hmac
    import hashlib
    if signature.startswith("sha256="):
        signature = signature[7:]
    expected = hmac.new(
        secret_value.encode("utf-8"),
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

        if not await verify_whatsapp_signature(raw_body, x_hub_signature_256):
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

@app.get("/brands/{brand_id}/poas")
async def get_brand_poas(brand_id: str, s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    brand = await s.get(Brand, brand_id)
    if not brand or brand.tenant_id != tid:
        raise HTTPException(404, "Brand not found")
    
    from app.profit.poas import calculate_campaign_poas
    reports = await calculate_campaign_poas(s, tid, brand_id)
    return {"brand_id": brand_id, "reports": reports}

@app.get("/brands/{brand_id}/performance-score")
async def get_brand_performance_score(brand_id: str, s: AsyncSession = Depends(get_db), tid: str = Depends(tenant_id)):
    brand = await s.get(Brand, brand_id)
    if not brand or brand.tenant_id != tid:
        raise HTTPException(404, "Brand not found")
    
    from app.profit.brand_score import calculate_brand_score
    score = await calculate_brand_score(s, tid, brand_id)
    return {"brand_id": brand_id, "performance_score": score}

@app.get("/metrics/brand-performance")
async def brand_performance(
    brand_id: str,
    w_ux: float | None = Query(default=None, ge=0.0, le=10.0),
    w_organic: float | None = Query(default=None, ge=0.0, le=10.0),
    w_paid: float | None = Query(default=None, ge=0.0, le=10.0),
    w_pr: float | None = Query(default=None, ge=0.0, le=10.0),
    s: AsyncSession = Depends(get_db),
    tid: str = Depends(tenant_id)
):
    """Computes the composite Brand Performance Score. Advisory only; read-only."""
    brand = await s.get(Brand, brand_id)
    if not brand or brand.tenant_id != tid:
        raise HTTPException(404, "Brand not found for tenant")

    from app.profit.brand_score import calculate_brand_performance_score
    score_report = await calculate_brand_performance_score(
        s,
        tenant_id=tid,
        brand_id=brand_id,
        w_ux=w_ux,
        w_organic=w_organic,
        w_paid=w_paid,
        w_pr=w_pr
    )
    return score_report


async def _find_connection(s: AsyncSession, provider: str, identifier: str) -> Connection | None:
    stmt = select(Connection).where(Connection.provider == provider)
    res = await s.execute(stmt)
    conns = res.scalars().all()
    for conn in conns:
        if provider == "shopify" and conn.config.get("shop_url") == identifier:
            return conn
    return None


@app.post("/webhooks/plugins/{provider}")
async def plugin_webhook(
    provider: str,
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None, alias="X-Shopify-Hmac-Sha256"),
    x_shopify_topic: str | None = Header(default=None, alias="X-Shopify-Topic"),
    s: AsyncSession = Depends(get_worker_db)
):
    try:
        plugin = get_plugin(provider)
        if not plugin:
            raise HTTPException(404, f"No plugin registered for provider: {provider}")

        headers = dict(request.headers)
        raw_body = await request.body()
        try:
            import json
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = {}

        # Deduplicate webhook using ProcessedWebhookMessage
        from app.models import ProcessedWebhookMessage
        from sqlalchemy.exc import IntegrityError
        webhook_id = headers.get("x-shopify-webhook-id") or headers.get("x-webhook-id") or headers.get("x-request-id")
        if webhook_id:
            try:
                async with s.begin_nested():
                    s.add(ProcessedWebhookMessage(message_id=webhook_id))
            except IntegrityError:
                logger.info(f"Duplicate plugin webhook message ID ignored: {webhook_id}")
                return {"status": "ignored", "detail": "duplicate webhook"}

        # 1. Resolve identifier
        identifier = await plugin.resolve_connection_identifier(headers, payload)
        if not identifier:
            raise HTTPException(400, "Unable to resolve connection identifier from webhook headers/payload")

        # 2. Find Connection (RLS is bypassed in get_worker_db session)
        conn = await _find_connection(s, provider, identifier)
        if not conn:
            raise HTTPException(404, f"Unknown brand connection for identifier: {identifier}")

        # Retrieve tenant to determine dedicated GCP project ID for secret isolation
        stmt_tenant = select(Tenant).where(Tenant.id == conn.tenant_id)
        res_tenant = await s.execute(stmt_tenant)
        tenant = res_tenant.scalar_one_or_none()
        gcp_project = tenant.gcp_project if tenant else None

        # 3. Retrieve signature and secret key
        signature = None
        if provider == "shopify":
            signature = x_shopify_hmac_sha256
        if not signature:
            signature = headers.get("x-signature")

        if not signature:
            raise HTTPException(401, "Webhook signature header missing")

        # Resolve actual secret key from Secret Manager (Falling back to secret_ref if not in Secret Manager)
        from app.services.secrets import SecretManagerClient
        try:
            secrets_client = SecretManagerClient(project_id=gcp_project)
            secret_key = await secrets_client.read_secret(conn.secret_ref)
        except ValueError as e:
            logger.warning(f"Secret not found in registry: {e}. Falling back to literal ref.")
            secret_key = conn.secret_ref
        except Exception as e:
            logger.error(f"Failed to read webhook secret from Secret Manager: {e}")
            raise HTTPException(500, "Internal secret resolution error")

        # 4. Verify signature
        if not await plugin.verify_signature(raw_body, signature, secret_key):
            raise HTTPException(401, "Webhook signature mismatch")

        # 5. Translate webhook payload to OpSpecs
        event_type = x_shopify_topic or headers.get("x-event-type", "")
        specs = await plugin.translate_webhook(event_type, payload, conn.tenant_id, conn.brand_id)

        proposed_ops = []
        # 6. Propose and gate each Op under the connection's tenant_id context
        token = tenant_context.set(conn.tenant_id)
        try:
            # Set app.current_tenant_id at the DB connection level for local RLS checks
            if s.bind.dialect.name == "postgresql":
                await s.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": conn.tenant_id},
                )

            for spec in specs:
                row = await loop.propose(s, spec, actor=f"webhook.{provider}")
                
                # Resolve trust snapshot to find tier
                from app.models import TrustSnapshot
                stmt_tier = (
                    select(TrustSnapshot.tier)
                    .where(
                        TrustSnapshot.tenant_id == conn.tenant_id,
                        TrustSnapshot.brand_id == conn.brand_id,
                        TrustSnapshot.domain == spec.domain
                    )
                    .order_by(TrustSnapshot.ts.desc())
                    .limit(1)
                )
                res_tier = await s.execute(stmt_tier)
                tier = res_tier.scalar_one_or_none()
                if tier is None:
                    tier = 1  # fallback to supervised

                await loop.preview_and_gate(s, row, tier=tier, actor=f"webhook.{provider}")
                proposed_ops.append(row.id)
                
            await s.commit()
        except Exception:
            await s.rollback()
            raise
        finally:
            tenant_context.reset(token)

        return {"status": "accepted", "proposed_ops": proposed_ops}
    except Exception as e:
        logger.exception("WEBHOOK EXCEPTION ENCOUNTERED:")
        raise


@app.get("/debug/db", dependencies=[Depends(verify_operator_auth)])
async def debug_db(s: AsyncSession = Depends(get_worker_db)):
    from app.models import OpRow, Tenant, OutboxItem
    
    res_policies = await s.execute(text("SELECT tablename, policyname, qual FROM pg_policies"))
    policies = [{"table": r[0], "name": r[1], "qual": r[2]} for r in res_policies.fetchall()]
    
    # Disable RLS temporarily
    await s.execute(text("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY"))
    await s.execute(text("ALTER TABLE ops DISABLE ROW LEVEL SECURITY"))
    
    try:
        res_tenants = await s.execute(select(Tenant))
        tenants = [{"id": t.id, "name": t.name} for t in res_tenants.scalars().all()]
        
        res_ops = await s.execute(select(OpRow))
        ops = [{"id": o.id, "tenant_id": o.tenant_id, "state": o.state, "action": o.action} for o in res_ops.scalars().all()]
    finally:
        # Guarantee RLS is re-enabled
        await s.execute(text("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY"))
        await s.execute(text("ALTER TABLE ops ENABLE ROW LEVEL SECURITY"))
    
    res_outbox = await s.execute(select(OutboxItem))
    outbox = [{"id": o.id, "op_id": o.op_id, "status": o.status} for o in res_outbox.scalars().all()]
    
    return {"tenants": tenants, "ops": ops, "outbox": outbox, "policies": policies}


@app.post("/debug/reset/{op_id}", dependencies=[Depends(verify_operator_auth)])
async def debug_reset(op_id: str, request: Request, s: AsyncSession = Depends(get_worker_db)):
    from app.models import OutboxItem, OpRow
    import datetime as dt
    
    tid = request.headers.get("X-Tenant-ID")
    if tid:
        await s.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": tid}
        )
        
    stmt = select(OutboxItem).where(OutboxItem.op_id == op_id)
    res = await s.execute(stmt)
    item = res.scalar_one_or_none()
    if item:
        item.status = "PENDING"
        item.attempts = 0
        item.next_attempt_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        
    stmt_op = select(OpRow).where(OpRow.id == op_id)
    res_op = await s.execute(stmt_op)
    row = res_op.scalar_one_or_none()
    if row and row.state in ("EXECUTING", "FAILED", "PARTIAL", "APPROVED", "ROLLED_BACK"):
        row.state = "APPROVED"
        
    await s.commit()
    return {"status": "ok", "message": f"Reset op {op_id} to PENDING/APPROVED"}


@app.get("/debug/raw", dependencies=[Depends(verify_operator_auth)])
async def debug_raw(s: AsyncSession = Depends(get_worker_db)):
    res_role = await s.execute(text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))
    role = res_role.fetchone()
    role_info = {
        "user": role[0] if role else None,
        "super": role[1] if role else None,
        "bypassrls": role[2] if role else None
    }
    
    res_session = await s.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
    session_val = res_session.scalar()
    
    res_ops = await s.execute(text("SELECT id, tenant_id, state, action FROM ops"))
    ops = [{"id": r[0], "tenant_id": r[1], "state": r[2], "action": r[3]} for r in res_ops.fetchall()]
    
    res_outbox = await s.execute(text("SELECT id, op_id, status FROM outbox"))
    outbox = [{"id": r[0], "op_id": r[1], "status": r[2]} for r in res_outbox.fetchall()]
    
    return {
        "role_info": role_info,
        "session_tenant_id": session_val,
        "ops": ops,
        "outbox": outbox
    }


@app.get("/debug/ops", dependencies=[Depends(verify_operator_auth)])
async def debug_ops(s: AsyncSession = Depends(get_worker_db)):
    res_owners = await s.execute(text("SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public'"))
    owners = {r[0]: r[1] for r in res_owners.fetchall()}
    
    await s.execute(text("SELECT set_config('app.current_tenant_id', '223d7d223e3e48df80db2b33ec45f802', true)"))
    res_a = await s.execute(text("SELECT id, tenant_id, brand_id, domain, action, state, parent_op_id FROM ops"))
    ops_a = [{"id": r[0], "tenant_id": r[1], "brand_id": r[2], "domain": r[3], "action": r[4], "state": r[5], "parent_op_id": r[6]} for r in res_a.fetchall()]
    
    await s.execute(text("SELECT set_config('app.current_tenant_id', '22307d223e3e48d58b4be2b33c43f802', true)"))
    res_b = await s.execute(text("SELECT id, tenant_id, brand_id, domain, action, state, parent_op_id FROM ops"))
    ops_b = [{"id": r[0], "tenant_id": r[1], "brand_id": r[2], "domain": r[3], "action": r[4], "state": r[5], "parent_op_id": r[6]} for r in res_b.fetchall()]
    
    return {
        "table_owners": owners,
        "ops_tenant_d": ops_a,
        "ops_tenant_0": ops_b
    }


@app.post("/debug/migrate", dependencies=[Depends(verify_operator_auth)])
async def debug_migrate(s: AsyncSession = Depends(get_db)):
    try:
        await s.execute(text("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(32)"))
        await s.execute(text("UPDATE outbox SET tenant_id = '22307d223e3e48d58b4be2b33c43f802' WHERE tenant_id IS NULL"))
        await s.commit()
        return {"status": "ok", "message": "Migration successful: added tenant_id and backfilled existing rows"}
    except Exception as e:
        await s.rollback()
        return {"status": "error", "message": f"Migration failed: {e}"}

