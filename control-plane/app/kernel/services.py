"""Kernel services: audit chain (§4.5), trust engine (§4.4), policy gates (§4.3).

INVARIANT (§2.1): nothing in this module consults a model. Gates are
deterministic and every rejection carries a structured explanation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
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
        
        # Reconcile naive and aware datetimes (common in SQLite tests)
        event_ts = ts
        if event_ts.tzinfo is None and now.tzinfo is not None:
            event_ts = event_ts.replace(tzinfo=dt.timezone.utc)
        elif event_ts.tzinfo is not None and now.tzinfo is None:
            event_ts = event_ts.replace(tzinfo=None)

        age_days = max(0.0, (now - event_ts).total_seconds() / 86400.0)
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

PROTECTED_PATHS = ["control-plane/", ".github/", "recipes/", "OWNERS", "METADATA"]
APPROVED_DEPENDENCIES = ["react", "react-dom", "next", "tailwindcss", "lucide-react"]

def _parse_diff_files(diff: str) -> list[str]:
    """Helper to extract modified file paths from a git diff."""
    files = []
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 4:
                file_a = parts[2][2:]
                files.append(file_a)
    return files

def _protected_paths_check(op: OpSpec) -> Optional[Violation]:
    diff = op.params.get("diff", "")
    modified_files = _parse_diff_files(diff)

    violated = []
    for f in modified_files:
        for p in PROTECTED_PATHS:
            if f.startswith(p):
                violated.append(f)
                break

    if violated:
        return Violation(
            rule_id="build_protected_paths",
            limit="No modifications to protected paths",
            attempted=", ".join(violated),
            delta="n/a",
            message=f"Attempted to modify protected paths: {', '.join(violated)}. "
                    f"Protected prefixes are: {', '.join(PROTECTED_PATHS)}"
        )
    return None

def _dependency_allowlist_check(op: OpSpec) -> Optional[Violation]:
    diff = op.params.get("diff", "")
    in_package_json = False
    added_deps = []

    for line in diff.splitlines():
        if line.startswith("diff --git a/package.json b/package.json"):
            in_package_json = True
            continue
        elif line.startswith("diff --git"):
            in_package_json = False
            continue

        if in_package_json and line.startswith("+") and not line.startswith("+++"):
            match = re.search(r'"([^"]+)"\s*:\s*"([^"]+)"', line)
            if match:
                dep_name = match.group(1)
                if dep_name not in ["name", "version", "description", "main", "license", "author"]:
                    added_deps.append(dep_name)

    unapproved = [d for d in added_deps if d not in APPROVED_DEPENDENCIES]
    if unapproved:
        return Violation(
            rule_id="build_dependency_allowlist",
            limit=f"Only approved dependencies: {', '.join(APPROVED_DEPENDENCIES)}",
            attempted=", ".join(unapproved),
            delta="n/a",
            message=f"Attempted to add unapproved dependencies: {', '.join(unapproved)}. "
                    f"Please request approval for these packages."
        )
    return None

def _secret_scan_check(op: OpSpec) -> Optional[Violation]:
    diff = op.params.get("diff", "")
    secret_patterns = [
        (r'AIza[0-9A-Za-z-_]{35}', "Google API Key"),
        (r'sk-proj-[0-9A-Za-z]{40}', "OpenAI Project API Key"),
        (r'-----BEGIN PRIVATE KEY-----', "Private Key"),
        (r'(?i)(password|secret|api_key|token)\s*=\s*["\'][^"\']{8,}["\']', "Potential hardcoded secret")
    ]
    violations = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            for pattern, name in secret_patterns:
                if re.search(pattern, line):
                    violations.append(name)
                    break
    if violations:
        return Violation(
            rule_id="build_secret_scan",
            limit="No hardcoded secrets allowed",
            attempted=", ".join(set(violations)),
            delta="n/a",
            message=f"Detected potential secrets in diff: {', '.join(set(violations))}. "
                    f"Use Secret Manager instead of hardcoding credentials."
        )
    return None

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
    Rule(
        id="build_protected_paths",
        applies=lambda op: op.domain == "build" and "diff" in op.params,
        check=_protected_paths_check,
        blocking=True
    ),
    Rule(
        id="build_dependency_allowlist",
        applies=lambda op: op.domain == "build" and "diff" in op.params,
        check=_dependency_allowlist_check,
        blocking=True
    ),
    Rule(
        id="build_secret_scan",
        applies=lambda op: op.domain == "build" and "diff" in op.params,
        check=_secret_scan_check,
        blocking=True
    ),
    Rule(
        id="statutory_region_lock",
        applies=lambda op: op.domain == "provision" and (op.statutory or "region" in op.params),
        check=lambda op: Violation(
            rule_id="statutory_region_lock",
            limit="region == asia-south1",
            attempted=op.params.get("region", "unknown"),
            delta="Non-compliant region",
            message="Statutory isolation rule: Resource must be deployed in asia-south1 (India) for data residency and GST compliance."
        ) if op.params.get("region") not in ("asia-south1", None) else None,
        blocking=False
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


async def compute_snapshots(s: AsyncSession, now: Optional[dt.datetime] = None):
    from ..models import Brand, TrustEvent, TrustSnapshot
    now = now or dt.datetime.now(dt.timezone.utc)

    # Get all brands
    res = await s.execute(select(Brand))
    brands = res.scalars().all()

    domains = ["provision", "build", "manage", "grow"]

    for brand in brands:
        for domain in domains:
            # Fetch events
            res_ev = await s.execute(
                select(TrustEvent).where(
                    TrustEvent.tenant_id == brand.tenant_id,
                    TrustEvent.brand_id == brand.id,
                    TrustEvent.domain == domain
                )
            )
            events = res_ev.scalars().all()
            event_tuples = [(e.kind, e.ts) for e in events]

            # Default signals (can hook up to real integration metrics later)
            signals = {"gtm_present": True, "pixel_present": True, "capi_dedup_rate": 0.9}

            score = trust_score(signals, event_tuples, now)
            tier = tier_for(score)

            snapshot = TrustSnapshot(
                tenant_id=brand.tenant_id,
                brand_id=brand.id,
                domain=domain,
                score=score,
                tier=tier,
                ts=now
            )
            s.add(snapshot)


# ---------------------------------------------------------------- cost ledger (§4.5)

async def emit_cost(s: AsyncSession, *, tenant_id: str, op_id: Optional[str] = None,
                    kind: str, amount_minor: int, currency: str = "INR",
                    meta: Optional[dict] = None, actor: Optional[str] = None) -> None:
    from ..models import CostEntry
    entry = CostEntry(
        op_id=op_id,
        tenant_id=tenant_id,
        actor=actor,
        kind=kind,
        amount_minor=amount_minor,
        currency=currency,
        meta=meta or {},
    )
    s.add(entry)
    await audit_append(s, tenant_id=tenant_id, actor=actor or "kernel", action=f"cost.{kind}",
                       op_id=op_id, payload={"amount_minor": amount_minor, "currency": currency})


async def get_tenant_cost_rollup(s: AsyncSession, tenant_id: str,
                                 start_time: Optional[dt.datetime] = None,
                                 end_time: Optional[dt.datetime] = None) -> dict[str, int]:
    """Returns total costs grouped by kind for a tenant."""
    from sqlalchemy import func
    from ..models import CostEntry
    stmt = (
        select(CostEntry.kind, func.sum(CostEntry.amount_minor))
        .where(CostEntry.tenant_id == tenant_id)
    )
    if start_time:
        stmt = stmt.where(CostEntry.ts >= start_time)
    if end_time:
        stmt = stmt.where(CostEntry.ts <= end_time)
    stmt = stmt.group_by(CostEntry.kind)
    
    res = await s.execute(stmt)
    return {kind: total for kind, total in res.all()}


async def get_op_cost_total(s: AsyncSession, op_id: str) -> int:
    """Returns the total cost accumulated by a single Op."""
    from sqlalchemy import func
    from ..models import CostEntry
    stmt = (
        select(func.sum(CostEntry.amount_minor))
        .where(CostEntry.op_id == op_id)
    )
    res = await s.execute(stmt)
    return res.scalar() or 0


async def ingest_gcp_billing(s: AsyncSession, *, tenant_id: str, resource_id: str,
                             amount_minor: int, currency: str = "INR",
                             labels: Optional[dict] = None) -> None:
    """Ingests a GCP billing record, attributing it to the tenant."""
    await emit_cost(
        s,
        tenant_id=tenant_id,
        kind="gcp_resource",
        amount_minor=amount_minor,
        currency=currency,
        meta={"resource_id": resource_id, "labels": labels or {}}
    )
