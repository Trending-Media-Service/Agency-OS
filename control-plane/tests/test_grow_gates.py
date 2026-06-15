import pytest
from app.kernel.services import evaluate_gates
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

def _build_reallocate_op(transfer_amount_minor: int) -> OpSpec:
    return OpSpec(
        id="op_reallocate_123",
        tenant_id="t1",
        brand_id="b1",
        domain="grow",
        action="grow.budget.reallocate",
        params={
            "transfer_amount_minor": transfer_amount_minor,
            "source_campaign_id": "camp-google",
            "target_campaign_id": "camp-meta"
        },
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR"),
    )

def test_grow_budget_transfer_cap_pass():
    # Limit is 5_000_000 (₹50,000). Propose ₹1,000 (100_000 minor)
    op = _build_reallocate_op(100_000)
    gate = evaluate_gates(op)
    assert not gate.blocked
    assert len(gate.violations) == 0

def test_grow_budget_transfer_cap_blocks_exceeding():
    # Propose ₹60,000 (6_000_000 minor)
    op = _build_reallocate_op(6_000_000)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert len(gate.violations) == 1
    assert gate.violations[0].rule_id == "grow_budget_transfer_cap"
    assert "exceeds" in gate.violations[0].message


def _build_bid_adjust_op(new_bid_minor: int) -> OpSpec:
    return OpSpec(
        id="op_bid_123",
        tenant_id="t1",
        brand_id="b1",
        domain="grow",
        action="grow.bid.adjust",
        params={
            "campaign_id": "camp-google",
            "new_bid_minor": new_bid_minor,
            "previous_bid_minor": 15000
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR"),
    )

def test_grow_bid_cap_pass():
    # Limit is 100_000 (₹1,000). Propose ₹500 (50_000 minor)
    op = _build_bid_adjust_op(50_000)
    gate = evaluate_gates(op)
    assert not gate.blocked
    assert len(gate.violations) == 0

def test_grow_bid_cap_blocks_exceeding():
    # Propose ₹1,200 (120_000 minor)
    op = _build_bid_adjust_op(120_000)
    gate = evaluate_gates(op)
    assert gate.blocked
    assert len(gate.violations) == 1
    assert gate.violations[0].rule_id == "grow_bid_cap"
    assert "exceeds" in gate.violations[0].message

