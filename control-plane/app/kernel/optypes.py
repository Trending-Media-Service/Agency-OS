"""Vendor-neutral kernel types. NO platform vocabulary in this module (ARCHITECTURE.md §2.4).

Domain vocabulary ("campaign", "bid", "cloud_run") lives in adapters only.
"""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


class Reversibility(str, enum.Enum):
    REVERSIBLE = "REVERSIBLE"          # exact undo exists
    COMPENSATABLE = "COMPENSATABLE"    # defined compensating action restores intent
    IRREVERSIBLE = "IRREVERSIBLE"      # e.g. sent message, registered domain


class OpState(str, enum.Enum):
    PROPOSED = "PROPOSED"
    PREVIEWED = "PREVIEWED"
    BLOCKED = "BLOCKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    ROLLED_BACK = "ROLLED_BACK"
    PARTIAL = "PARTIAL"


# Allowed transitions — ARCHITECTURE.md §4.1. Anything not listed is illegal.
ALLOWED_TRANSITIONS: dict[OpState, set[OpState]] = {
    OpState.PROPOSED: {OpState.PREVIEWED},
    OpState.PREVIEWED: {OpState.AWAITING_APPROVAL, OpState.BLOCKED, OpState.APPROVED},
    # PREVIEWED -> APPROVED only via tier-2 auto-approval inside policy gates.
    OpState.AWAITING_APPROVAL: {
        OpState.APPROVED,
        OpState.REJECTED,
        OpState.EXPIRED,
        OpState.PREVIEWED,  # A2UI modification re-enters preview after re-plan
    },
    OpState.APPROVED: {OpState.EXECUTING},
    OpState.EXECUTING: {OpState.VERIFYING, OpState.FAILED, OpState.PARTIAL},
    OpState.VERIFYING: {OpState.DONE, OpState.FAILED, OpState.PARTIAL},
    OpState.FAILED: {OpState.COMPENSATING},
    OpState.COMPENSATING: {OpState.ROLLED_BACK, OpState.PARTIAL},
    # Terminal: DONE, REJECTED, EXPIRED, BLOCKED, ROLLED_BACK. PARTIAL parks for operator.
    OpState.BLOCKED: set(),
    OpState.REJECTED: set(),
    OpState.EXPIRED: set(),
    OpState.DONE: {OpState.COMPENSATING},
    OpState.ROLLED_BACK: set(),
    OpState.PARTIAL: {OpState.COMPENSATING, OpState.EXECUTING},  # operator-driven resume
}


class InvalidTransition(Exception):
    def __init__(self, current: OpState, target: OpState):
        super().__init__(f"illegal transition {current.value} -> {target.value}")
        self.current, self.target = current, target


def assert_transition(current: OpState, target: OpState) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(current, target)


@dataclass(frozen=True)
class Money:
    amount_minor: int  # paise / cents
    currency: str = "INR"

    def __str__(self) -> str:
        return f"{self.amount_minor / 100:.2f} {self.currency}"


@dataclass(frozen=True)
class Severity:
    """Two-factor severity (ARCHITECTURE.md §4.3): impact band x reversibility.

    impact: 1 (trivial) .. 5 (existential). Domain-scaled by the adapter.
    """
    impact: int
    reversibility: Reversibility

    def __post_init__(self):
        if not 1 <= self.impact <= 5:
            raise ValueError("impact must be 1..5")


@dataclass(frozen=True)
class OpSpec:
    """The universal, vendor-neutral operation contract (§5)."""
    tenant_id: str
    brand_id: str
    domain: str                      # provision | build | manage | grow
    action: str                      # adapter-namespaced, e.g. "provision.web_host.create"
    params: dict[str, Any]
    severity: Severity
    cost_estimate: Optional[Money] = None
    parent_op_id: Optional[str] = None
    sequence_order: int = 0
    statutory: bool = False          # §2.2 statutory firewall flag
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def idem_key(self) -> str:
        return self.id  # one Op == one idempotency key (§4.2)


@dataclass(frozen=True)
class PreviewArtifact:
    kind: str        # "terraform_plan" | "staging_url" | "diff" | "summary"
    summary: str     # human-readable; rendered verbatim on approval cards
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    detail: str = ""
