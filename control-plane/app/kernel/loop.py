"""The governed action loop (§4.1) + transactional outbox (§4.2) + adapter registry (§5)."""
from __future__ import annotations

import datetime as dt
import json
import logging

logger = logging.getLogger(__name__)
import re
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Approval, OpRow, OpTrace, OutboxItem, TrustEvent, CircuitBreakerRow, OpDependency
from .optypes import (ExecResult, Money, OpSpec, OpState, PreviewArtifact,
                      Reversibility, Severity, VerifyResult, assert_transition)
from .services import (GateResult, TRUST_CONFIG, approval_requirement, audit_append,
                       evaluate_gates, load_active_rules, check_role_authority,
                       load_active_ruleset_params, build_rules, check_consent_gate)


class Adapter(Protocol):
    domain: str
    def plan(self, intent: str, tenant_id: str, brand_id: str) -> list[OpSpec]: ...
    def preview(self, op: OpSpec) -> PreviewArtifact: ...
    async def execute(self, op: OpSpec, idem_key: str, session: Optional[AsyncSession] = None) -> ExecResult: ...
    async def verify(self, op: OpSpec) -> VerifyResult: ...
    def compensate(self, op: OpSpec) -> list[OpSpec]: ...


class RBACError(ValueError):
  """Raised when an actor attempts to approve an Op without sufficient authority."""
  pass


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


def trace(s: AsyncSession, op_id: str, tenant_id: str, kind: str, detail: dict) -> None:
    s.add(OpTrace(op_id=op_id, tenant_id=tenant_id, kind=kind, detail=detail))


async def transition(s: AsyncSession, row: OpRow, target: OpState, *, actor: str, detail: Optional[dict] = None) -> None:
    current = OpState(row.state)
    assert_transition(current, target)
    row.state = target.value
    trace(s, row.id, row.tenant_id, "transition", {"from": current.value, "to": target.value, **(detail or {})})
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

    # Create OpDependency rows
    if spec.parent_op_id:
        if spec.depends_on is not None:
            for dep_id in spec.depends_on:
                s.add(OpDependency(
                    tenant_id=spec.tenant_id,
                    parent_op_id=spec.parent_op_id,
                    from_op_id=dep_id,
                    to_op_id=spec.id
                ))
        elif spec.sequence_order > 1:
            # Fallback to sequence_order chaining: find previous sibling in the parent saga
            stmt = select(OpRow.id).where(
                OpRow.parent_op_id == spec.parent_op_id,
                OpRow.sequence_order == spec.sequence_order - 1
            )
            res = await s.execute(stmt)
            prev_id = res.scalar_one_or_none()
            if prev_id:
                s.add(OpDependency(
                    tenant_id=spec.tenant_id,
                    parent_op_id=spec.parent_op_id,
                    from_op_id=prev_id,
                    to_op_id=spec.id
                ))

    return row


async def preview_and_gate(s: AsyncSession, row: OpRow, *, tier: int, actor: str = "kernel") -> tuple[GateResult, str]:
    """PROPOSED -> PREVIEWED -> (AWAITING_APPROVAL | APPROVED(auto) | BLOCKED)."""
    spec = _row_to_spec(row)
    adapter = REGISTRY[row.domain]

    artifact = adapter.preview(spec)
    row.preview_summary = artifact.summary
    trace(s, row.id, row.tenant_id, "preview", {"kind": artifact.kind})
    if row.state != OpState.PREVIEWED.value:
        await transition(s, row, OpState.PREVIEWED, actor=actor)

    rules = await load_active_rules(s, row.tenant_id)
    gate = evaluate_gates(spec, rules=rules)
    
    consent_violation = await check_consent_gate(s, row.tenant_id, spec)
    if consent_violation:
        gate.violations.append(consent_violation)
        gate.blocked = True
        
    trace(s, row.id, row.tenant_id, "gate", {"violations": [v.as_dict() for v in gate.violations],
                              "requires_human": gate.requires_human})
    requirement = approval_requirement(spec, tier, gate)

    if requirement == "BLOCKED":
        await transition(s, row, OpState.BLOCKED, actor=actor,
                   detail={"violations": [v.as_dict() for v in gate.violations], "tier": tier})
    elif requirement == "AUTO":
        await transition(s, row, OpState.APPROVED, actor="kernel:tier2-auto",
                   detail={"tier": tier})
        s.add(Approval(op_id=row.id, tenant_id=row.tenant_id, actor="kernel", role="tier2-auto",
                       surface="auto", decision="approve"))
        enqueue(s, row.id)
    else:
        await transition(s, row, OpState.AWAITING_APPROVAL, actor=actor, detail={"tier": tier})
    return gate, requirement


async def check_cooldown(s: AsyncSession, row: OpRow, window_seconds: int = 86400) -> bool:
    """Returns True if execution is allowed (no cooldown active), False if blocked by cooldown."""
    try:
        # Resolve target ID from params
        target_id = None
        if "campaign_id" in row.params:
            target_id = row.params["campaign_id"]
        elif "db_name" in row.params:
            target_id = row.params["db_name"]
        elif "recipe" in row.params:
            target_id = row.params["recipe"]
        else:
            target_id = json.dumps(row.params, sort_keys=True)

        since_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=window_seconds)

        # Query recent similar DONE ops: same brand, same domain, same action, after since_time
        stmt = select(OpRow).where(
            OpRow.tenant_id == row.tenant_id,
            OpRow.brand_id == row.brand_id,
            OpRow.domain == row.domain,
            OpRow.action == row.action,
            OpRow.state == "DONE",
            OpRow.created_at >= since_time,
            OpRow.id != row.id
        )
        res = await s.execute(stmt)
        recent_ops = res.scalars().all()

        for op in recent_ops:
            # Check if target matches
            op_target_id = None
            if "campaign_id" in op.params:
                op_target_id = op.params["campaign_id"]
            elif "db_name" in op.params:
                op_target_id = op.params["db_name"]
            elif "recipe" in op.params:
                op_target_id = op.params["recipe"]
            else:
                op_target_id = json.dumps(op.params, sort_keys=True)

            if op_target_id == target_id:
                logger.warning(f"Action blocked by cooldown limit: domain={row.domain}, action={row.action}, target={target_id}")
                return False
        return True
    except Exception as e:
        logger.error(f"Failsafe: Error checking cooldown status, allowing execution. Error: {e}")
        return True


async def is_circuit_tripped(s: AsyncSession, tenant_id: str, brand_id: str, domain: str, reset_timeout_seconds: int = 900) -> bool:
    """Returns True if circuit breaker is currently OPEN, False if CLOSED."""
    try:
        stmt = select(CircuitBreakerRow).where(
            CircuitBreakerRow.tenant_id == tenant_id,
            CircuitBreakerRow.brand_id == brand_id,
            CircuitBreakerRow.domain == domain
        )
        res = await s.execute(stmt)
        breaker = res.scalar_one_or_none()
        if not breaker:
            return False

        if breaker.state == "OPEN":
            # Auto-reset check
            if breaker.tripped_at:
                now = dt.datetime.now(dt.timezone.utc)
                tripped = breaker.tripped_at.replace(tzinfo=None)
                current = now.replace(tzinfo=None)
                if (current - tripped).total_seconds() >= reset_timeout_seconds:
                    logger.info(f"Circuit breaker reset timeout reached. Testing HALF_OPEN for domain {domain}")
                    breaker.state = "CLOSED"
                    breaker.consecutive_failures = 0
                    await s.commit()
                    return False
            return True
        return False
    except Exception as e:
        logger.error(f"Failsafe: Error checking circuit breaker state, allowing execution. Error: {e}")
        return False


async def record_failure(s: AsyncSession, tenant_id: str, brand_id: str, domain: str, max_failures: int = 3):
    """Increments failures count and opens the circuit if threshold is reached."""
    try:
        stmt = select(CircuitBreakerRow).where(
            CircuitBreakerRow.tenant_id == tenant_id,
            CircuitBreakerRow.brand_id == brand_id,
            CircuitBreakerRow.domain == domain
        )
        res = await s.execute(stmt)
        breaker = res.scalar_one_or_none()
        if not breaker:
            breaker = CircuitBreakerRow(
                tenant_id=tenant_id,
                brand_id=brand_id,
                domain=domain,
                consecutive_failures=0,
                state="CLOSED"
            )
            s.add(breaker)

        breaker.consecutive_failures += 1
        breaker.last_failure_at = dt.datetime.now(dt.timezone.utc)

        if breaker.consecutive_failures >= max_failures:
            breaker.state = "OPEN"
            breaker.tripped_at = dt.datetime.now(dt.timezone.utc)
            logger.error(f"Circuit breaker TRIPPED (OPEN) for domain {domain} due to {breaker.consecutive_failures} consecutive failures.")

        await s.commit()
    except Exception as e:
        logger.error(f"Failed to record failure in circuit breaker: {e}")


async def record_success(s: AsyncSession, tenant_id: str, brand_id: str, domain: str):
    """Resets the circuit breaker metrics to CLOSED state on success."""
    try:
        stmt = select(CircuitBreakerRow).where(
            CircuitBreakerRow.tenant_id == tenant_id,
            CircuitBreakerRow.brand_id == brand_id,
            CircuitBreakerRow.domain == domain
        )
        res = await s.execute(stmt)
        breaker = res.scalar_one_or_none()
        if breaker:
            breaker.consecutive_failures = 0
            breaker.state = "CLOSED"
            await s.commit()
    except Exception as e:
        logger.error(f"Failed to record success in circuit breaker: {e}")


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
    normalized = tweak_text.lower()

    # 1. Domain tweak
    match_domain = re.search(r'\b([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,})\b', normalized)
    if match_domain:
        new_params["domain"] = match_domain.group(1)

    # 2. Grow Budget tweak (e.g. "budget to 4000")
    match_budget = re.search(r'budget\s*(?:to|:|=)?\s*([0-9]+(?:\.[0-9]+)?)', normalized)
    if match_budget:
        try:
            budget_val = float(match_budget.group(1))
            new_params["budget_minor"] = int(budget_val * 100)
        except ValueError:
            pass

    # 3. Grow Bid tweak (e.g. "bid to 40")
    match_bid = re.search(r'bid\s*(?:to|:|=)?\s*([0-9]+(?:\.[0-9]+)?)', normalized)
    if match_bid:
        try:
            bid_val = float(match_bid.group(1))
            new_params["bid_minor"] = int(bid_val * 100)
        except ValueError:
            pass

    return new_params


async def _decision_latency_ms(s: AsyncSession, op_id: str) -> Optional[int]:
    """Ms from card delivery (WhatsApp) — else the AWAITING_APPROVAL transition —
    to the decision. The north-star clock (§1). Best-effort: None if no marker.
    Read-only; does not affect the decision."""
    res = await s.execute(select(OpTrace).where(OpTrace.op_id == op_id).order_by(OpTrace.id))
    traces = res.scalars().all()
    start = None
    for t in traces:  # prefer the actual card-delivery time when present
        if t.kind == "whatsapp_card_sent":
            start = t.ts
    if start is None:
        for t in traces:
            if t.kind == "transition" and (t.detail or {}).get("to") == OpState.AWAITING_APPROVAL.value:
                start = t.ts
                break
    if start is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    if start.tzinfo is None:  # sqlite stores naive; treat as UTC
        start = start.replace(tzinfo=dt.timezone.utc)
    return max(0, int((now - start).total_seconds() * 1000))


async def decide(s: AsyncSession, row: OpRow, *, decision: str, actor: str, role: str,
           surface: str, reason: Optional[str] = None,
           latency_ms: Optional[int] = None) -> None:
    if latency_ms is None:  # populate the north-star metric (§1); never gates
        latency_ms = await _decision_latency_ms(s, row.id)
    s.add(Approval(op_id=row.id, tenant_id=row.tenant_id, actor=actor, role=role, surface=surface,
                   decision=decision, reason=reason, latency_ms=latency_ms))
    if decision == "approve":
        spec = _row_to_spec(row)
        params = await load_active_ruleset_params(s, row.tenant_id)
        
        # Enforce role authority boundaries
        auth_error = check_role_authority(spec, role, params)
        if auth_error:
            logger.warning(f"RBAC Violation: {auth_error} (actor={actor}, op_id={row.id})")
            raise RBACError(auth_error)

        rules = build_rules(params)
        gate = evaluate_gates(spec, rules=rules)
        if gate.violations:
            if not reason or not reason.strip():
                raise ValueError("Override reason is mandatory for approved ops with policy violations")
            emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "override", reason=reason)
        
        # Fetch children
        res_children = await s.execute(select(OpRow).where(OpRow.parent_op_id == row.id))
        children = res_children.scalars().all()
        if children:
            await transition(s, row, OpState.APPROVED, actor=actor)
            for child in children:
                await transition(s, child, OpState.APPROVED, actor=actor)
            
            # Find root children (no incoming dependencies)
            stmt_non_roots = select(OpDependency.to_op_id).where(OpDependency.parent_op_id == row.id)
            res_non_roots = await s.execute(stmt_non_roots)
            non_root_ids = set(res_non_roots.scalars().all())
            
            for child in children:
                if child.id not in non_root_ids:
                    enqueue(s, child.id)
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
        old_params = row.params.copy() if row.params else {}
        new_params = apply_tweak(row.domain, row.action, row.params, reason or "")
        row.params = new_params

        # Update cost_amount_minor if budget was tweaked
        if "budget_minor" in new_params and row.cost_amount_minor is not None:
            row.cost_amount_minor = new_params["budget_minor"]

        # Transition back to PREVIEWED with correct old params
        await transition(s, row, OpState.PREVIEWED, actor=actor, detail={"reason": reason or "", "params_before": old_params})

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
    from app.observability import trace_context
    trace_id = trace_context.get()
    s.add(OutboxItem(op_id=op_id, trace_id=trace_id))  # same txn as the APPROVED transition (§4.2)


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
        from app.observability import trace_context
        token = trace_context.set(item.trace_id)
        try:
            row = await s.get(OpRow, item.op_id)
            if not row:
                item.status = "DEAD"
                processed += 1
                continue

            if OpState(row.state) in (OpState.FAILED, OpState.ROLLED_BACK, OpState.REJECTED, OpState.BLOCKED):
                item.status = "DEAD"
                processed += 1
                continue

            # 1. Cooldown Check
            is_cooldown_ok = await check_cooldown(s, row)
            if not is_cooldown_ok:
                item.status = "DEAD"
                await transition(s, row, OpState.BLOCKED, actor="cooldown",
                                 detail={"error": "Operation cooldown active. A similar action was recently completed."})
                processed += 1
                continue

            # 2. Circuit Breaker Check
            is_tripped = await is_circuit_tripped(s, row.tenant_id, row.brand_id, row.domain)
            if is_tripped:
                item.status = "DEAD"
                await transition(s, row, OpState.BLOCKED, actor="circuit_breaker",
                                 detail={"error": f"Adapter execution BLOCKED. Circuit breaker is OPEN for domain {row.domain}."})
                processed += 1
                continue

            item.status = "IN_FLIGHT"
            item.attempts += 1
            await _execute_and_verify(s, row)
            item.status = "DONE"

            # Reset Circuit Breaker failures on success
            await record_success(s, row.tenant_id, row.brand_id, row.domain)
        except Exception as exc:  # noqa: BLE001 — park, never crash the drain
            logger.exception(f"Drain execution error on op {row.id}")
            trace(s, row.id, row.tenant_id, "retry", {"attempt": item.attempts, "error": str(exc)})
            
            # Record failure in Circuit Breaker
            await record_failure(s, row.tenant_id, row.brand_id, row.domain)

            if item.attempts >= 5:
                item.status = "DEAD"
                if OpState(row.state) in (OpState.EXECUTING, OpState.VERIFYING):
                    await transition(s, row, OpState.PARTIAL, actor="kernel",
                               detail={"error": str(exc)})
            else:
                item.status = "PENDING"
                item.next_attempt_at = now + dt.timedelta(seconds=2 ** item.attempts)
        finally:
            trace_context.reset(token)
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
    result = await adapter.execute(spec, idem_key=row.idem_key, session=s)
    trace(s, row.id, row.tenant_id, "adapter_call", {"phase": "execute", "ok": result.ok, **result.detail})

    # Record any execution costs returned by the adapter
    if hasattr(result, "costs") and result.costs:
        # Resolve the actor who approved this execution
        target_op_id = row.parent_op_id if row.parent_op_id else row.id
        stmt_app = select(Approval).where(Approval.op_id == target_op_id, Approval.decision == "approve").limit(1)
        res_app = await s.execute(stmt_app)
        approval = res_app.scalar_one_or_none()
        approver = approval.actor if approval else "kernel"

        from app.kernel.services import emit_cost
        for cost in result.costs:
            await emit_cost(
                s,
                tenant_id=row.tenant_id,
                op_id=row.id,
                kind=cost.kind,
                amount_minor=cost.amount_minor,
                currency=cost.currency,
                meta=cost.meta,
                actor=approver
            )
    if not result.ok:
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "verify_failure",
                         reason=f"Execution failed: {result.detail.get('error')}")
        await transition(s, row, OpState.FAILED, actor="kernel", detail=result.detail)
        # Propagate failure to parent, cancel siblings, and trigger rollback cascade
        if row.parent_op_id:
            parent = await s.get(OpRow, row.parent_op_id)
            if parent:
                await transition(s, parent, OpState.FAILED, actor="kernel", detail={"failed_child_id": row.id})
                await cancel_active_siblings(s, row)
                await trigger_saga_rollback(s, row.parent_op_id)
        await _compensate(s, row, adapter, spec)
        return

    await transition(s, row, OpState.VERIFYING, actor="kernel")
    verdict = await adapter.verify(spec)
    trace(s, row.id, row.tenant_id, "adapter_call", {"phase": "verify", "ok": verdict.ok,
                                      "checks": verdict.checks})
    if verdict.ok:
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "verified_success")
        await transition(s, row, OpState.DONE, actor="kernel")

        # SAGA SEQUENCING (DAG):
        if row.parent_op_id:
            # Find children that depend on this completed child
            stmt = select(OpDependency.to_op_id).where(OpDependency.from_op_id == row.id)
            res = await s.execute(stmt)
            dependent_op_ids = res.scalars().all()
            for dep_id in dependent_op_ids:
                # Check if all dependencies for dep_id are DONE
                stmt_all_deps = select(OpDependency.from_op_id).where(OpDependency.to_op_id == dep_id)
                res_all_deps = await s.execute(stmt_all_deps)
                required_op_ids = res_all_deps.scalars().all()
                
                stmt_states = select(OpRow).where(OpRow.id.in_(required_op_ids))
                res_states = await s.execute(stmt_states)
                dep_rows = res_states.scalars().all()
                
                if all(d.state == OpState.DONE.value for d in dep_rows):
                    enqueue(s, dep_id)
            
            # Check if all children of the parent are DONE
            stmt_all_children = select(OpRow).where(OpRow.parent_op_id == row.parent_op_id)
            res_all_children = await s.execute(stmt_all_children)
            all_children = res_all_children.scalars().all()
            if all(c.state == OpState.DONE.value for c in all_children):
                parent = await s.get(OpRow, row.parent_op_id)
                if parent:
                    await transition(s, parent, OpState.VERIFYING, actor="kernel")
                    await transition(s, parent, OpState.DONE, actor="kernel")
    else:
        emit_trust_event(s, row.tenant_id, row.brand_id, row.domain, "verify_failure",
                         reason=f"Verification checks failed: {verdict.checks}")
        await transition(s, row, OpState.FAILED, actor="kernel",
                   detail={"checks": verdict.checks, "note": verdict.detail})
        # Propagate failure to parent, cancel siblings, and trigger rollback cascade
        if row.parent_op_id:
            parent = await s.get(OpRow, row.parent_op_id)
            if parent:
                await transition(s, parent, OpState.FAILED, actor="kernel", detail={"failed_child_id": row.id})
                await cancel_active_siblings(s, row)
                await trigger_saga_rollback(s, row.parent_op_id)
        await _compensate(s, row, adapter, spec)


async def cancel_active_siblings(s: AsyncSession, failed_child: OpRow):
    stmt = select(OpRow).where(
        OpRow.parent_op_id == failed_child.parent_op_id,
        OpRow.id != failed_child.id,
        OpRow.state.in_([OpState.APPROVED.value, OpState.EXECUTING.value, OpState.VERIFYING.value])
    )
    res = await s.execute(stmt)
    active_siblings = res.scalars().all()
    for sib in active_siblings:
        prev_state = sib.state
        # Move state to FAILED
        await transition(s, sib, OpState.FAILED, actor="kernel", detail={"note": "Cancelled due to sibling failure"})
        # If it was active (executing/verifying), compensate it
        if prev_state in (OpState.EXECUTING.value, OpState.VERIFYING.value):
            adapter = REGISTRY[sib.domain]
            spec = _row_to_spec(sib)
            await _compensate(s, sib, adapter, spec)
        elif prev_state == OpState.APPROVED.value:
            # For unexecuted APPROVED siblings, transition them cleanly to ROLLED_BACK via COMPENSATING without adapter calls
            await transition(s, sib, OpState.COMPENSATING, actor="kernel")
            await transition(s, sib, OpState.ROLLED_BACK, actor="kernel")


async def trigger_saga_rollback(s: AsyncSession, parent_id: str):
    res = await s.execute(select(OpRow).where(OpRow.parent_op_id == parent_id))
    children = res.scalars().all()
    
    for child in children:
        if child.state == OpState.DONE.value:
            stmt_deps = select(OpRow).where(
                OpRow.id.in_(
                    select(OpDependency.to_op_id).where(OpDependency.from_op_id == child.id)
                )
            )
            res_deps = await s.execute(stmt_deps)
            deps = res_deps.scalars().all()
            
            if all(d.state in (OpState.ROLLED_BACK.value, OpState.FAILED.value, OpState.REJECTED.value) for d in deps):
                adapter = REGISTRY[child.domain]
                spec = _row_to_spec(child)
                await _compensate(s, child, adapter, spec)


async def _compensate(s: AsyncSession, row: OpRow, adapter: Adapter, spec: OpSpec) -> None:
    await transition(s, row, OpState.COMPENSATING, actor="kernel")
    comp_ops = adapter.compensate(spec)
    trace(s, row.id, row.tenant_id, "note", {"compensation_ops": [c.action for c in comp_ops]})
    
    if row.state != OpState.COMPENSATING.value:
        await transition(s, row, OpState.COMPENSATING, actor="kernel")

    # Execute compensations if returned
    for comp in comp_ops:
        res = await adapter.execute(comp, idem_key=comp.idem_key or f"comp-{row.id}", session=s)
        trace(s, row.id, row.tenant_id, "compensation_call", {"action": comp.action, "ok": res.ok, **res.detail})

    await transition(s, row, OpState.ROLLED_BACK, actor="kernel")

    # SAGA ROLLBACK SEQUENCING (DAG):
    if row.parent_op_id:
        stmt = select(OpDependency.from_op_id).where(OpDependency.to_op_id == row.id)
        res = await s.execute(stmt)
        required_ids = res.scalars().all()
        
        for y_id in required_ids:
            y_row = await s.get(OpRow, y_id)
            if y_row and y_row.state == OpState.DONE.value:
                # Check if all outbound dependents of Y are compensated (ROLLED_BACK, FAILED, or REJECTED)
                stmt_dependents = select(OpRow).where(
                    OpRow.id.in_(
                        select(OpDependency.to_op_id).where(OpDependency.from_op_id == y_id)
                    )
                )
                res_deps = await s.execute(stmt_dependents)
                deps = res_deps.scalars().all()
                if all(d.state in (OpState.ROLLED_BACK.value, OpState.FAILED.value, OpState.REJECTED.value) for d in deps):
                    prev_adapter = REGISTRY[y_row.domain]
                    prev_spec = _row_to_spec(y_row)
                    await _compensate(s, y_row, prev_adapter, prev_spec)
        
        # Transition parent to ROLLED_BACK if no DONE children remain
        stmt_done = select(OpRow).where(OpRow.parent_op_id == row.parent_op_id, OpRow.state == OpState.DONE.value)
        res_done = await s.execute(stmt_done)
        if not res_done.scalars().first():
            parent = await s.get(OpRow, row.parent_op_id)
            if parent and parent.state not in (OpState.COMPENSATING.value, OpState.ROLLED_BACK.value):
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
