"""Control-plane API. Tenant assertion on every request (§3); the conversational
interface proposes Ops only — all authority lives in the kernel (§7)."""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .kernel import loop
from .kernel.services import audit_verify
from .models import Brand, OpRow, OpTrace, Tenant, make_engine, make_session_factory

engine = make_engine(os.environ.get("AOS_DB_URL", "sqlite:///./agencyos.db"))
SessionFactory = make_session_factory(engine)
app = FastAPI(title="Agency OS control plane", version="0.1.0")


def db():
    s = SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(401, "X-Tenant-Id header required")
    return x_tenant_id


class TenantIn(BaseModel):
    name: str
    brand_name: str


@app.post("/tenants")
def create_tenant(body: TenantIn, s: Session = Depends(db)):
    t = Tenant(name=body.name)
    s.add(t); s.flush()
    b = Brand(tenant_id=t.id, name=body.brand_name)
    s.add(b); s.flush()
    return {"tenant_id": t.id, "brand_id": b.id}


class IntentIn(BaseModel):
    brand_id: str
    text: str
    domain: str = "provision"
    tier: int = 1  # trust-engine wiring is a Slice 1 issue; explicit until then


@app.post("/intents")
def submit_intent(body: IntentIn, s: Session = Depends(db), tid: str = Depends(tenant_id)):
    adapter = loop.REGISTRY.get(body.domain)
    if not adapter:
        raise HTTPException(400, f"no adapter for domain {body.domain!r}")
    cards = []
    for spec in adapter.plan(body.text, tid, body.brand_id):
        row = loop.propose(s, spec, actor="chat")
        gate, requirement = loop.preview_and_gate(s, row, tier=body.tier)
        cards.append({
            "op_id": row.id, "action": row.action, "state": row.state,
            "requirement": requirement,
            "preview": row.preview_summary,
            "cost_estimate": (f"{row.cost_amount_minor/100:.2f} {row.cost_currency}/mo"
                              if row.cost_amount_minor else None),
            "violations": [v.as_dict() for v in gate.violations],
        })
    return {"cards": cards}


class DecisionIn(BaseModel):
    decision: str  # approve | reject
    actor: str
    role: str = "AGENCY_OWNER"
    surface: str = "web"
    reason: str | None = None


@app.post("/ops/{op_id}/decision")
def decide(op_id: str, body: DecisionIn, s: Session = Depends(db), tid: str = Depends(tenant_id)):
    row = s.get(OpRow, op_id)
    if not row or row.tenant_id != tid:
        raise HTTPException(404, "op not found for tenant")
    loop.decide(s, row, decision=body.decision, actor=body.actor, role=body.role,
                surface=body.surface, reason=body.reason)
    loop.drain_once(s)  # v1 inline drain; Cloud Tasks worker replaces this call site
    s.flush()
    return {"op_id": row.id, "state": row.state}


@app.get("/ops/{op_id}")
def get_op(op_id: str, s: Session = Depends(db), tid: str = Depends(tenant_id)):
    row = s.get(OpRow, op_id)
    if not row or row.tenant_id != tid:
        raise HTTPException(404, "op not found for tenant")
    traces = [
        {"ts": t.ts.isoformat(), "kind": t.kind, "detail": t.detail}
        for t in s.query(OpTrace).filter_by(op_id=op_id).order_by(OpTrace.id)
    ]
    return {"op_id": row.id, "action": row.action, "state": row.state,
            "preview": row.preview_summary, "trace": traces}


@app.get("/audit/verify")
def verify_audit(s: Session = Depends(db)):
    ok, first_bad = audit_verify(s)
    return {"ok": ok, "first_bad_id": first_bad}
