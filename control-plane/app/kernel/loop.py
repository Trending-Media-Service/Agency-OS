"""The governed action loop (§4.1) + transactional outbox (§4.2) + adapter registry (§5)."""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, OpRow, OpTrace, OutboxItem, TrustEvent
from .optypes import (ExecResult, Money, OpSpec, OpState, PreviewArtifact,
                      Reversibility, Severity, VerifyResult, assert_transition)
from .services import (GateResult, TRUST_CONFIG, approval_requirement, audit_append,
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
        parent_op_id=row.parent_op_id, sequence_order=row.sequence_order, statutory=row.statutory,
    )


def trace(s: AsyncSession, op_id: str, kind: str, detail: dict) -> None:
    s.add(OpTrace(op_id=op_id, kind=kind, detail=detail))


async def transition(s: AsyncSession, row: OpRow, target: OpState, *, actor: str, detail: Optional[dict] = None) -> None:
    current = OpState(row.state)
    assert_transition(current, target)
    row.state = target.value
    trace(s, row.id, "transition", {"from": current.value, "to": target.value, **(detail or {})})
    await audit_append(s, tenant_id=row.tenant_id, actor=actor,
                 action=f"op.{target.value.lower()}", op_id=row.id, payload=detail or {})


async def propose(s: AsyncSession, spec: OpSpec, *, actor: str) -> OpRow:
    row = OpRow(
        id=spec.id, tenant_id=spec.tenant_id, brand_id=spec.brand_id,
        domain=spec.domain, action=spec.action, params=spec.params,
        state=OpState.PROPOSED.value, impact=spec.severity.impact,
        reversibility=spec.severity.reversibility.value, statutory=spec.statutory,
        cost_amount_minor=spec.cost_estimate.amount_minor if spec.cost_estimate else None,
        cost_currency=spec.cost_estimate.currency if spec.cost_estimate else None,
        parent_op_id=spec.parent_op_id, sequence_order=spec.sequence_order, idem_key=spec.idem_key,
    )
    s.add(row)
    await audit_append(s, tenant_id=spec.tenant_id, actor=actor, action="op.proposed",
                 op_id=spec.id, payload={"action": spec.action})
    return row


async def preview_and_gate(s: AsyncSession, row: OpRow, *, tier: int, actor: str = "kernel") -> tuple[GateResult, str]:
    """PROPOSED -> PREVIEWED -> (AWAITING_APPROVAL | APPROVED(auto) | BLOCKED)."""
    spec = _row_to_spec(row)
    adapter = REGISTRY[row.domain]

    artifact = adapter.preview(spec)
    row.preview_summary = artifact.summary
    trace(s, row.id, "preview", {"kind": artifact.kind})
    if row.state != OpState.PREVIEWED.value:
        await transition(s, row, OpState.PREVIEWED, actor=actor)

    gate = evaluate_gates(spec)
    trace(s, row.id, "gate", {"violations": [v.as_dict() for v in gate.violations],
                              "requires_human": gate.requires_human})
    requirement = approval_requirement(spec, tier, gate)

    if requirement == "BLOCKED":
        await transition(s, row, OpState.BLOCKED, actor=actor,
                   detail={"violations": [v.as_dict() for v in gate.violations], "tier": tier})
    elif requirement == "AUTO":
        await transition(s, row, OpState.APPROVED, actor="kernel:tier2-auto",
                   detail={"tier": tier})
        s.add(Approval(op_id=row.id, actor="kernel", role="tier2-auto",
                       surface="auto", decision="approve"))
        enqueue(s, row.id)
    else:
        await transition(s, row, OpState.AWAITING_APPROVAL, actor=actor, detail={"tier": tier})
    return gate, requirement


def emit_trust_event(s: AsyncSession, tenant_id: str, brand_id: str, domain: str, kind: str, reason: Optional[str] = None):
    delta = TRUST_CONFIG["history"]["deltas"].get(kind, 0.0)
    s.add(TrustEvent(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain=domain,
        kind=kind,
        base_delta=delta,
        reason=reason
    ))


def apply_tweak(domain: str, action: str, params: dict, tweak_text: str) -> dict:
    new_params = dict(params)
    # Match domain names like woktok.co, google.com, etc.
    match = re.search(r'\b([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,})\b', tweak_text.lower())
    if match:
        new_params["domain"] = match.group(1)
    return new_params


async def decide(s: AsyncSession, row: OpRow, *, decision: str, actor: str, role: str,
           surface: str, reason: Optional[str] = None,
           latency_ms: Optional[int] = None) -> None:
    s.add(Approval(op_id=row.id, actor=actor, role=role, surface=surface,
                   decision=decision, reason=reason, latency_ms=latency_ms))
    if decision == "approve":
        spec = _row_to_spec(row)
        gate = evaluate_gates(spec)
        if gate.violations:
            if not reason or not reason.strip():
                raise ValueError("Override reason is mandatory for approved ops with policy violations")
            emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "override", reason=reason)
        
        # Fetch children
        res_children = await s.execute(select(OpRow).where(OpRow.parent_op_id == row.id).order_by(OpRow.sequence_order))
        children = res_children.scalars().all()
        if children:
            await transition(s, row, OpState.APPROVED, actor=actor)
            for child in children:
                await transition(s, child, OpState.APPROVED, actor=actor)
            enqueue(s, children[0].id)
        else:
            await transition(s, row, OpState.APPROVED, actor=actor)
            enqueue(s, row.id)
    elif decision == "reject":
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "rejection", reason=reason)
        await transition(s, row, OpState.REJECTED, actor=actor, detail={"reason": reason or ""})
        # Propagate rejection to children
        res_children = await s.execute(select(OpRow).where(OpRow.parent_op_id == row.id))
        for child in res_children.scalars().all():
            await transition(s, child, OpState.REJECTED, actor=actor, detail={"reason": "Parent Op rejected"})
    elif decision == "modify":
        # Apply tweak to parameters
        new_params = apply_tweak(row.domain, row.action, row.params, reason or "")
        row.params = new_params

        # Transition back to PREVIEWED
        await transition(s, row, OpState.PREVIEWED, actor=actor, detail={"reason": reason or "", "params_before": row.params})

        # Resolve tier from latest snapshot
        from ..models import TrustSnapshot
        stmt = (
            select(TrustSnapshot.tier)
            .where(
                TrustSnapshot.tenant_id == row.tenant_id,
                TrustSnapshot.brand_id == row.brand_id,
                TrustSnapshot.domain == row.domain
            )
            .order_by(TrustSnapshot.ts.desc())
            .limit(1)
        )
        res = await s.execute(stmt)
        tier = res.scalar_one_or_none()
        if tier is None:
            tier = 1

        # Re-run preview and gate
        await preview_and_gate(s, row, tier=tier, actor=actor)
    else:
        raise ValueError(f"unknown decision {decision!r}")

# ------------------------------------------------------------------- outbox

def enqueue(s: AsyncSession, op_id: str) -> None:
    s.add(OutboxItem(op_id=op_id))  # same txn as the APPROVED transition (§4.2)


async def drain_once(s: AsyncSession, *, now: Optional[dt.datetime] = None, max_items: int = 10) -> int:
    """v1 in-process drain. Cloud Tasks worker replaces the call site, not the logic."""
    now = now or dt.datetime.now(dt.timezone.utc)
    await s.flush()  # stamp defaults on same-txn enqueues BEFORE the cutoff comparison
    now = max(now, dt.datetime.now(dt.timezone.utc))
    result = await s.execute(
        select(OutboxItem).where(OutboxItem.status == "PENDING",
                                 OutboxItem.next_attempt_at <= now)
        .order_by(OutboxItem.id).limit(max_items))
    items = result.scalars().all()
    processed = 0
    for item in items:
        row = await s.get(OpRow, item.op_id)
        item.status = "IN_FLIGHT"
        item.attempts += 1
        try:
            await _execute_and_verify(s, row)
            item.status = "DONE"
        except Exception as exc:  # noqa: BLE001 — park, never crash the drain
            trace(s, row.id, "retry", {"attempt": item.attempts, "error": str(exc)})
            if item.attempts >= 5:
                item.status = "DEAD"
                if OpState(row.state) in (OpState.EXECUTING, OpState.VERIFYING):
                    await transition(s, row, OpState.PARTIAL, actor="kernel",
                               detail={"error": str(exc)})
            else:
                item.status = "PENDING"
                item.next_attempt_at = now + dt.timedelta(seconds=2 ** item.attempts)
        processed += 1
    return processed


async def _execute_and_verify(s: AsyncSession, row: OpRow) -> None:
    spec = _row_to_spec(row)
    adapter = REGISTRY[row.domain]

    # If this is a child Op, and the parent is still APPROVED, transition parent to EXECUTING
    if row.parent_op_id:
        parent = await s.get(OpRow, row.parent_op_id)
        if parent and parent.state == OpState.APPROVED.value:
            await transition(s, parent, OpState.EXECUTING, actor="kernel")

    await transition(s, row, OpState.EXECUTING, actor="kernel")
    result = adapter.execute(spec, idem_key=row.idem_key)
    trace(s, row.id, "adapter_call", {"phase": "execute", "ok": result.ok, **result.detail})

    # Record any execution costs returned by the adapter
    if hasattr(result, "costs") and result.costs:
        from app.kernel.services import emit_cost
        for cost in result.costs:
            await emit_cost(
                s,
                tenant_id=row.tenant_id,
                op_id=row.id,
                kind=cost.kind,
                amount_minor=cost.amount_minor,
                currency=cost.currency,
                meta=cost.meta
            )
    if not result.ok:
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "verify_failure",
                         reason=f"Execution failed: {result.detail.get('error')}")
        await transition(s, row, OpState.FAILED, actor="kernel", detail=result.detail)
        # Propagate failure to parent
        if row.parent_op_id:
            parent = await s.get(OpRow, row.parent_op_id)
            if parent:
                await transition(s, parent, OpState.FAILED, actor="kernel", detail={"failed_child_id": row.id})
        await _compensate(s, row, adapter, spec)
        return

    await transition(s, row, OpState.VERIFYING, actor="kernel")
    verdict = adapter.verify(spec)
    trace(s, row.id, "adapter_call", {"phase": "verify", "ok": verdict.ok,
                                      "checks": verdict.checks})
    if verdict.ok:
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "verified_success")
        await transition(s, row, OpState.DONE, actor="kernel")

        # SAGA SEQUENCING:
        if row.parent_op_id:
            # Find next child of the same parent
            stmt = (
                select(OpRow)
                .where(
                    OpRow.parent_op_id == row.parent_op_id,
                    OpRow.sequence_order > row.sequence_order
                )
                .order_by(OpRow.sequence_order.asc())
                .limit(1)
            )
            res = await s.execute(stmt)
            next_child = res.scalar_one_or_none()
            if next_child:
                enqueue(s, next_child.id)
            else:
                # No more children! Transition parent to DONE via VERIFYING
                parent = await s.get(OpRow, row.parent_op_id)
                if parent:
                    await transition(s, parent, OpState.VERIFYING, actor="kernel")
                    await transition(s, parent, OpState.DONE, actor="kernel")
    else:
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "verify_failure",
                         reason=f"Verification checks failed: {verdict.checks}")
        await transition(s, row, OpState.FAILED, actor="kernel",
                   detail={"checks": verdict.checks, "note": verdict.detail})
        # Propagate failure to parent
        if row.parent_op_id:
            parent = await s.get(OpRow, row.parent_op_id)
            if parent:
                await transition(s, parent, OpState.FAILED, actor="kernel", detail={"failed_child_id": row.id})
        await _compensate(s, row, adapter, spec)


async def _compensate(s: AsyncSession, row: OpRow, adapter: Adapter, spec: OpSpec) -> None:
    await transition(s, row, OpState.COMPENSATING, actor="kernel")
    comp_ops = adapter.compensate(spec)
    trace(s, row.id, "note", {"compensation_ops": [c.action for c in comp_ops]})
    
    # Execute compensations if returned
    for comp in comp_ops:
        res = adapter.execute(comp, idem_key=comp.idem_key or f"comp-{row.id}")
        trace(s, row.id, "compensation_call", {"action": comp.action, "ok": res.ok, **res.detail})

    await transition(s, row, OpState.ROLLED_BACK, actor="kernel")

    # SAGA ROLLBACK SEQUENCING:
    if row.parent_op_id:
        # Find the previous child that completed successfully (is in DONE state)
        stmt = (
            select(OpRow)
            .where(
                OpRow.parent_op_id == row.parent_op_id,
                OpRow.sequence_order < row.sequence_order,
                OpRow.state == OpState.DONE.value
            )
            .order_by(OpRow.sequence_order.desc())
            .limit(1)
        )
        res = await s.execute(stmt)
        prev_child = res.scalar_one_or_none()
        if prev_child:
            # Trigger compensation for the previous child
            prev_adapter = REGISTRY[prev_child.domain]
            prev_spec = _row_to_spec(prev_child)
            await _compensate(s, prev_child, prev_adapter, prev_spec)
        else:
            # No more completed children! Transition parent to ROLLED_BACK via COMPENSATING
            parent = await s.get(OpRow, row.parent_op_id)
            if parent:
                await transition(s, parent, OpState.COMPENSATING, actor="kernel")
                await transition(s, parent, OpState.ROLLED_BACK, actor="kernel")


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
