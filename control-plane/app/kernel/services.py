"""Kernel services: audit chain (§4.5), trust engine (§4.4), policy gates (§4.3).

INVARIANT (§2.1): nothing in this module consults a model. Gates are
deterministic and every rejection carries a structured explanation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .optypes import OpSpec, Reversibility

GENESIS = "0" * 64

# ---------------------------------------------------------------- audit chain

def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


async def audit_append(s: AsyncSession, *, tenant_id: str, actor: str, action: str,
                 op_id: Optional[str] = None, payload: Optional[dict] = None):
    from ..models import AuditEvent
    result = await s.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
    last = result.scalar_one_or_none()
    prev_hash = last.hash if last else GENESIS
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    preimage = prev_hash + "|" + _canonical(
        {"ts": ts, "tenant_id": tenant_id, "actor": actor, "action": action,
         "op_id": op_id, "payload": payload or {}})
    h = hashlib.sha256(preimage.encode()).hexdigest()
    ev = AuditEvent(ts=ts, tenant_id=tenant_id, actor=actor, action=action,
                    op_id=op_id, payload=payload or {}, prev_hash=prev_hash, hash=h)
    s.add(ev)
    return ev


async def audit_verify(s: AsyncSession) -> tuple[bool, Optional[int]]:
    """Walk the chain; return (ok, first_bad_id)."""
    from ..models import AuditEvent
    prev = GENESIS
    result = await s.execute(select(AuditEvent).order_by(AuditEvent.id.asc()))
    for ev in result.scalars():
        preimage = prev + "|" + _canonical(
            {"ts": ev.ts, "tenant_id": ev.tenant_id, "actor": ev.actor,
             "action": ev.action, "op_id": ev.op_id, "payload": ev.payload})
        if ev.prev_hash != prev or hashlib.sha256(preimage.encode()).hexdigest() != ev.hash:
            return False, ev.id
        prev = ev.hash
    return True, None

# ---------------------------------------------------------------- trust (§4.4)
# Provisional config — versioned here, tuned on real Ableys data (§11.4).
TRUST_CONFIG = {
    "health_weights": {"gtm_present": 20.0, "pixel_present": 20.0, "capi_dedup_rate": 30.0},  # max 70
    "penalties": {  # saturating: p_max * (1 - e^(-count/tau))
        "gmc_critical_mismatches": {"p_max": 25.0, "tau": 5.0},
        "reputation_alerts": {"p_max": 20.0, "tau": 2.0},
    },
    "history": {  # event deltas decay with half-life; contribution clamped
        "deltas": {"verified_success": +1.0, "override": -5.0,
                   "verify_failure": -8.0, "rejection": -2.0},
        "half_life_days": 45.0,
        "clamp": 30.0,
    },
    "tiers": {"lockout_below": 60.0, "autonomy_at": 85.0},
}


def saturating_penalty(count: int, p_max: float, tau: float) -> float:
    """Bounded, monotone, distinguishes 5 from 50 (fixes the unbounded-subtraction
    defect in both the legacy prototype and the pasted enterprise doc)."""
    if count <= 0:
        return 0.0
    return p_max * (1.0 - math.exp(-count / tau))


def health_score(signals: dict) -> float:
    w = TRUST_CONFIG["health_weights"]
    score = 0.0
    score += w["gtm_present"] if signals.get("gtm_present") else 0.0
    score += w["pixel_present"] if signals.get("pixel_present") else 0.0
    score += w["capi_dedup_rate"] * max(0.0, min(1.0, float(signals.get("capi_dedup_rate", 0.0))))
    return score


def signal_penalties(signals: dict) -> float:
    total = 0.0
    for key, cfg in TRUST_CONFIG["penalties"].items():
        total += saturating_penalty(int(signals.get(key, 0)), cfg["p_max"], cfg["tau"])
    return total


def history_score(events: list[tuple[str, dt.datetime]], now: dt.datetime) -> float:
    """events: (kind, ts). Exponential decay; clamped to +/- clamp."""
    cfg = TRUST_CONFIG["history"]
    hl, clamp = cfg["half_life_days"], cfg["clamp"]
    total = 0.0
    for kind, ts in events:
        base = cfg["deltas"].get(kind, 0.0)
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        total += base * (0.5 ** (age_days / hl))
    return max(-clamp, min(clamp, total))


def trust_score(signals: dict, events: list[tuple[str, dt.datetime]],
                now: Optional[dt.datetime] = None) -> float:
    now = now or dt.datetime.now(dt.timezone.utc)
    s = health_score(signals) - signal_penalties(signals) + history_score(events, now)
    return max(0.0, min(100.0, s))


def tier_for(score: float) -> int:
    t = TRUST_CONFIG["tiers"]
    if score < t["lockout_below"]:
        return 0
    if score >= t["autonomy_at"]:
        return 2
    return 1

# ---------------------------------------------------------------- policy (§4.3)

@dataclass(frozen=True)
class Violation:
    rule_id: str
    limit: str
    attempted: str
    delta: str
    message: str  # rendered verbatim on cards — no generic errors

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class GateResult:
    blocked: bool = False
    requires_human: bool = False
    violations: list[Violation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Rule:
    id: str
    applies: Callable[[OpSpec], bool]
    check: Callable[[OpSpec], Optional[Violation]]
    blocking: bool = True  # non-blocking rules force human approval instead


def _statutory_check(op: OpSpec) -> Optional[Violation]:
    return Violation(
        rule_id="statutory_firewall", limit="auto-execution: never",
        attempted=op.action, delta="n/a",
        message="Statutory/tax-adjacent operation: human approval is mandatory at "
                "every trust tier (ARCHITECTURE.md §2.2).")


STATUTORY_MARKERS = (".tax.", ".gst.", ".vat.", ".statutory.")

DEFAULT_RULES: list[Rule] = [
    Rule(
        id="statutory_firewall",
        applies=lambda op: op.statutory or any(m in op.action for m in STATUTORY_MARKERS),
        check=_statutory_check,
        blocking=False,  # never auto-approve; does not block human-approved execution
    ),
    Rule(
        id="provision_cost_ceiling",
        applies=lambda op: op.domain == "provision" and op.cost_estimate is not None,
        check=lambda op: Violation(
            rule_id="provision_cost_ceiling",
            limit="<= 10,000.00 INR/month",
            attempted=str(op.cost_estimate),
            delta=f"+{(op.cost_estimate.amount_minor - 1_000_000) / 100:.2f} INR over ceiling",
            message="Estimated monthly cost exceeds the provisioning ceiling; raise the "
                    "ceiling via a policy-change Op or reduce the plan.",
        ) if op.cost_estimate.amount_minor > 1_000_000 else None,
    ),
    Rule(
        id="grow_bid_cap",
        applies=lambda op: op.action == "grow.bid.adjust",
        check=lambda op: Violation(
            rule_id="grow_bid_cap", limit="new_bid <= 1000.00 INR",
            attempted=f"{op.params.get('new_bid_minor', 0) / 100:.2f} INR",
            delta=f"+{(op.params.get('new_bid_minor', 0) - 100_000) / 100:.2f} INR over cap",
            message="Bid exceeds the per-adjustment cap.",
        ) if op.params.get("new_bid_minor", 0) > 100_000 else None,
    ),
    Rule(
        id="grow_budget_transfer_cap",
        applies=lambda op: op.action == "grow.budget.reallocate",
        check=lambda op: Violation(
            rule_id="grow_budget_transfer_cap", limit="amount <= 50,000.00 INR",
            attempted=f"{op.params.get('amount_minor', 0) / 100:.2f} INR",
            delta=f"+{(op.params.get('amount_minor', 0) - 5_000_000) / 100:.2f} INR over cap",
            message="Budget transfer exceeds the per-action cap.",
        ) if op.params.get("amount_minor", 0) > 5_000_000 else None,
    ),
]


def evaluate_gates(op: OpSpec, rules: Optional[list[Rule]] = None) -> GateResult:
    result = GateResult()
    for rule in (rules if rules is not None else DEFAULT_RULES):
        if not rule.applies(op):
            continue
        v = rule.check(op)
        if v is None:
            continue
        result.violations.append(v)
        if rule.blocking:
            result.blocked = True
        else:
            result.requires_human = True
    return result


def approval_requirement(op: OpSpec, tier: int, gate: GateResult) -> str:
    """AUTO | HUMAN | BLOCKED — deterministic (§2.1). Tier 2 auto-approval only
    within gates, impact <= 2, never irreversible, never statutory-flagged."""
    if gate.blocked:
        return "BLOCKED"
    if tier == 0:
        return "BLOCKED"  # lockout: state-changing Ops do not proceed
    if (tier == 2 and not gate.requires_human and op.severity.impact <= 2
            and op.severity.reversibility != Reversibility.IRREVERSIBLE):
        return "AUTO"
    return "HUMAN"
