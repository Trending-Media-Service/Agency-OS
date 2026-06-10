"""The governed action loop (§4.1) + transactional outbox (§4.2) + adapter registry (§5)."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Approval, OpRow, OpTrace, OutboxItem
from .optypes import (ExecResult, Money, OpSpec, OpState, PreviewArtifact,
                      Reversibility, Severity, VerifyResult, assert_transition)
from .services import (GateResult, approval_requirement, audit_append,
                       evaluate_gates)


class Adapter(Protocol):
    domain: str
    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]: ...
    def preview(self, op: OpSpec) -> PreviewArtifact: ...
    def execute(self, op: OpSpec, idem_key: str) -> ExecResult: ...
    def verify(self, op: OpSpec) -> VerifyResult: ...
    def compensate(self, op: OpSpec) -> list[OpSpec]: ...


REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    REGISTRY[adapter.domain] = adapter


def _row_to_spec(row: OpRow) -> OpSpec:
    return OpSpec(
        id=row.id, tenant_id=row.tenant_id, brand_id=row.brand_id,
        domain=row.domain, action=row.action, params=row.params,
        severity=Severity(row.impact, Reversibility(row.reversibility)),
        cost_estimate=(Money(row.cost_amount_minor, row.cost_currency)
                       if row.cost_amount_minor is not None else None),
        parent_op_id=row.parent_op_id, statutory=row.statutory,
    )


def trace(s: Session, op_id: str, kind: str, detail: dict) -> None:
    s.add(OpTrace(op_id=op_id, kind=kind, detail=detail))


def transition(s: Session, row: OpRow, target: OpState, *, actor: str, detail: Optional[dict] = None) -> None:
    current = OpState(row.state)
    assert_transition(current, target)
    row.state = target.value
    trace(s, row.id, "transition", {"from": current.value, "to": target.value, **(detail or {})})
    audit_append(s, tenant_id=row.tenant_id, actor=actor,
                 action=f"op.{target.value.lower()}", op_id=row.id, payload=detail or {})


def propose(s: Session, spec: OpSpec, *, actor: str) -> OpRow:
    row = OpRow(
        id=spec.id, tenant_id=spec.tenant_id, brand_id=spec.brand_id,
        domain=spec.domain, action=spec.action, params=spec.params,
        state=OpState.PROPOSED.value, impact=spec.severity.impact,
        reversibility=spec.severity.reversibility.value, statutory=spec.statutory,
        cost_amount_minor=spec.cost_estimate.amount_minor if spec.cost_estimate else None,
        cost_currency=spec.cost_estimate.currency if spec.cost_estimate else None,
        parent_op_id=spec.parent_op_id, idem_key=spec.idem_key,
    )
    s.add(row)
    audit_append(s, tenant_id=spec.tenant_id, actor=actor, action="op.proposed",
                 op_id=spec.id, payload={"action": spec.action})
    return row


def preview_and_gate(s: Session, row: OpRow, *, tier: int, actor: str = "kernel") -> tuple[GateResult, str]:
    """PROPOSED -> PREVIEWED -> (AWAITING_APPROVAL | APPROVED(auto) | BLOCKED)."""
    spec = _row_to_spec(row)
    adapter = REGISTRY[row.domain]

    artifact = adapter.preview(spec)
    row.preview_summary = artifact.summary
    trace(s, row.id, "preview", {"kind": artifact.kind})
    transition(s, row, OpState.PREVIEWED, actor=actor)

    gate = evaluate_gates(spec)
    trace(s, row.id, "gate", {"violations": [v.as_dict() for v in gate.violations],
                              "requires_human": gate.requires_human})
    requirement = approval_requirement(spec, tier, gate)

    if requirement == "BLOCKED":
        transition(s, row, OpState.BLOCKED, actor=actor,
                   detail={"violations": [v.as_dict() for v in gate.violations], "tier": tier})
    elif requirement == "AUTO":
        transition(s, row, OpState.APPROVED, actor="kernel:tier2-auto",
                   detail={"tier": tier})
        s.add(Approval(op_id=row.id, actor="kernel", role="tier2-auto",
                       surface="auto", decision="approve"))
        enqueue(s, row.id)
    else:
        transition(s, row, OpState.AWAITING_APPROVAL, actor=actor, detail={"tier": tier})
    return gate, requirement


def decide(s: Session, row: OpRow, *, decision: str, actor: str, role: str,
           surface: str, reason: Optional[str] = None,
           latency_ms: Optional[int] = None) -> None:
    s.add(Approval(op_id=row.id, actor=actor, role=role, surface=surface,
                   decision=decision, reason=reason, latency_ms=latency_ms))
    if decision == "approve":
        transition(s, row, OpState.APPROVED, actor=actor)
        enqueue(s, row.id)
    elif decision == "reject":
        transition(s, row, OpState.REJECTED, actor=actor, detail={"reason": reason or ""})
    else:
        raise ValueError(f"unknown decision {decision!r} (A2UI 'modify' is a Slice-1 issue)")

# ------------------------------------------------------------------- outbox

def enqueue(s: Session, op_id: str) -> None:
    s.add(OutboxItem(op_id=op_id))  # same txn as the APPROVED transition (§4.2)


def drain_once(s: Session, *, now: Optional[dt.datetime] = None, max_items: int = 10) -> int:
    """v1 in-process drain. Cloud Tasks worker replaces the call site, not the logic."""
    now = now or dt.datetime.now(dt.timezone.utc)
    s.flush()  # stamp defaults on same-txn enqueues BEFORE the cutoff comparison
    now = max(now, dt.datetime.now(dt.timezone.utc))
    items = s.execute(
        select(OutboxItem).where(OutboxItem.status == "PENDING",
                                 OutboxItem.next_attempt_at <= now)
        .order_by(OutboxItem.id).limit(max_items)).scalars().all()
    processed = 0
    for item in items:
        row = s.get(OpRow, item.op_id)
        item.status = "IN_FLIGHT"
        item.attempts += 1
        try:
            _execute_and_verify(s, row)
            item.status = "DONE"
        except Exception as exc:  # noqa: BLE001 — park, never crash the drain
            trace(s, row.id, "retry", {"attempt": item.attempts, "error": str(exc)})
            if item.attempts >= 5:
                item.status = "DEAD"
                if OpState(row.state) in (OpState.EXECUTING, OpState.VERIFYING):
                    transition(s, row, OpState.PARTIAL, actor="kernel",
                               detail={"error": str(exc)})
            else:
                item.status = "PENDING"
                item.next_attempt_at = now + dt.timedelta(seconds=2 ** item.attempts)
        processed += 1
    return processed


def _execute_and_verify(s: Session, row: OpRow) -> None:
    spec = _row_to_spec(row)
    adapter = REGISTRY[row.domain]

    transition(s, row, OpState.EXECUTING, actor="kernel")
    result = adapter.execute(spec, idem_key=row.idem_key)
    trace(s, row.id, "adapter_call", {"phase": "execute", "ok": result.ok, **result.detail})
    if not result.ok:
        transition(s, row, OpState.FAILED, actor="kernel", detail=result.detail)
        _compensate(s, row, adapter, spec)
        return

    transition(s, row, OpState.VERIFYING, actor="kernel")
    verdict = adapter.verify(spec)
    trace(s, row.id, "adapter_call", {"phase": "verify", "ok": verdict.ok,
                                      "checks": verdict.checks})
    if verdict.ok:
        transition(s, row, OpState.DONE, actor="kernel")
    else:
        transition(s, row, OpState.FAILED, actor="kernel",
                   detail={"checks": verdict.checks, "note": verdict.detail})
        _compensate(s, row, adapter, spec)


def _compensate(s: Session, row: OpRow, adapter: Adapter, spec: OpSpec) -> None:
    transition(s, row, OpState.COMPENSATING, actor="kernel")
    comp_ops = adapter.compensate(spec)
    trace(s, row.id, "note", {"compensation_ops": [c.action for c in comp_ops]})
    # Compensations are themselves Ops (§4.1); for the v1 stub they are no-ops.
    transition(s, row, OpState.ROLLED_BACK, actor="kernel")


# ------------------------------------------------- demo provision adapter (§6.1)

class DemoProvisionAdapter:
    """Drives the loop end-to-end with a fake Terraform plan. Replaced by the
    real recipe executor (Slice 1 issue: terraform plan/apply wrapper)."""
    domain = "provision"

    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]:
        domain_name = next((w for w in intent.replace(",", " ").split()
                            if "." in w and not w.startswith(".")), "example.in")
        return [OpSpec(
            tenant_id=tenant_id, brand_id=brand_id, domain=self.domain,
            action="provision.web_host.create",
            params={"domain": domain_name, "recipe": "web-host", "version": "0.1.0"},
            severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
            cost_estimate=Money(amount_minor=250_000, currency="INR"),  # ~2,500/mo shared tier
        )]

    def preview(self, op: OpSpec) -> PreviewArtifact:
        d = op.params["domain"]
        return PreviewArtifact(
            kind="terraform_plan",
            summary=(f"Plan: 5 to add, 0 to change, 0 to destroy\n"
                     f"+ cloud_dns zone {d}\n+ managed SSL cert {d}\n"
                     f"+ cloud_run service web-{d.split('.')[0]} (shared tier)\n"
                     f"+ budget alert\n+ service account"),
            detail={"resources": 5})

    def execute(self, op: OpSpec, idem_key: str) -> ExecResult:
        return ExecResult(ok=True, detail={"applied": 5, "idem_key": idem_key})

    def verify(self, op: OpSpec) -> VerifyResult:
        return VerifyResult(ok=True, checks={"dns_resolves": True, "cert_issued": True,
                                             "http_200": True})

    def compensate(self, op: OpSpec) -> list[OpSpec]:
        return [OpSpec(tenant_id=op.tenant_id, brand_id=op.brand_id,
                       domain=self.domain, action="provision.web_host.destroy",
                       params=op.params,
                       severity=Severity(impact=2, reversibility=Reversibility.IRREVERSIBLE),
                       parent_op_id=op.id)]


register(DemoProvisionAdapter())
