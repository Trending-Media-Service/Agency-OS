"""Kernel tests. The e2e test at the bottom is the Slice 1 heartbeat:
intent -> preview -> gate -> approval -> outbox -> execute -> verify -> DONE,
with the audit chain intact.
"""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.main as mainmod
from app.kernel import loop
from app.kernel.optypes import (InvalidTransition, Money, OpSpec, OpState,
                                Reversibility, Severity, assert_transition)
from app.kernel.services import (audit_append, audit_verify, evaluate_gates,
                                 approval_requirement, saturating_penalty,
                                 tier_for, trust_score)
from app.models import AuditEvent, make_engine, make_session_factory

NOW = dt.datetime(2026, 6, 10, tzinfo=dt.timezone.utc)


@pytest.fixture()
def session():
    factory = make_session_factory(make_engine("sqlite://"))
    s = factory()
    yield s
    s.close()


def _spec(**kw) -> OpSpec:
    base = dict(tenant_id="t1", brand_id="b1", domain="provision",
                action="provision.web_host.create", params={"domain": "x.in"},
                severity=Severity(2, Reversibility.COMPENSATABLE),
                cost_estimate=Money(250_000))
    base.update(kw)
    return OpSpec(**base)

# ----------------------------------------------------------- state machine

def test_state_machine_blocks_illegal_jumps():
    with pytest.raises(InvalidTransition):
        assert_transition(OpState.PROPOSED, OpState.EXECUTING)  # no gate-skipping
    with pytest.raises(InvalidTransition):
        assert_transition(OpState.DONE, OpState.EXECUTING)      # terminal is terminal
    assert_transition(OpState.AWAITING_APPROVAL, OpState.PREVIEWED)  # A2UI re-plan

# ------------------------------------------------------------- audit chain

def test_audit_chain_verifies_and_detects_tamper(session: Session):
    for i in range(5):
        audit_append(session, tenant_id="t1", actor="test", action=f"e{i}")
    session.flush()
    assert audit_verify(session) == (True, None)

    victim = session.query(AuditEvent).filter_by(action="e2").one()
    victim.payload = {"injected": True}  # tamper
    session.flush()
    ok, first_bad = audit_verify(session)
    assert ok is False and first_bad == victim.id

# ------------------------------------------------------------------ trust

def test_saturating_penalty_is_bounded_and_discriminating():
    p5 = saturating_penalty(5, p_max=25, tau=5)
    p50 = saturating_penalty(50, p_max=25, tau=5)
    assert p5 < p50 <= 25.0          # 5 vs 50 mismatches are distinguishable
    assert saturating_penalty(10_000, p_max=25, tau=5) <= 25.0  # never -infinity


def test_cold_start_lands_in_tier1_by_design():
    """Perfect health, zero history = 70 -> Tier 1. Autonomy is EARNED (§4.4)."""
    score = trust_score({"gtm_present": True, "pixel_present": True,
                         "capi_dedup_rate": 1.0}, events=[], now=NOW)
    assert score == pytest.approx(70.0)
    assert tier_for(score) == 1


def test_history_decays_and_overrides_are_recoverable():
    signals = {"gtm_present": True, "pixel_present": True, "capi_dedup_rate": 1.0}
    fresh = trust_score(signals, [("override", NOW - dt.timedelta(days=1))], now=NOW)
    stale = trust_score(signals, [("override", NOW - dt.timedelta(days=90))], now=NOW)
    assert fresh < stale  # the same mistake matters less with time
    # 5 recent overrides must not nuke the score to zero (legacy defect fixed):
    many = trust_score(signals, [("override", NOW)] * 5, now=NOW)
    assert many >= 40.0


def test_earned_autonomy_reaches_tier2():
    signals = {"gtm_present": True, "pixel_present": True, "capi_dedup_rate": 1.0}
    events = [("verified_success", NOW - dt.timedelta(days=i)) for i in range(20)]
    score = trust_score(signals, events, now=NOW)
    assert score >= 85.0 and tier_for(score) == 2

# ----------------------------------------------------------------- policy

def test_statutory_firewall_never_auto_approves():
    op = _spec(action="manage.gst.filing_update", statutory=True,
               severity=Severity(1, Reversibility.REVERSIBLE), cost_estimate=None,
               domain="manage")
    gate = evaluate_gates(op)
    assert gate.requires_human and not gate.blocked
    assert approval_requirement(op, tier=2, gate=gate) == "HUMAN"  # even at Tier 2


def test_cost_ceiling_blocks_with_structured_explanation():
    op = _spec(cost_estimate=Money(2_000_000))  # 20,000 INR > 10,000 ceiling
    gate = evaluate_gates(op)
    assert gate.blocked
    v = gate.violations[0]
    assert v.rule_id == "provision_cost_ceiling"
    assert "10,000.00" in v.limit and "over ceiling" in v.delta  # rule/limit/delta (§4.3)


def test_tier2_auto_approval_only_within_bounds():
    ok_op = _spec()  # impact 2, compensatable, within cost ceiling
    gate = evaluate_gates(ok_op)
    assert approval_requirement(ok_op, tier=2, gate=gate) == "AUTO"

    irreversible = _spec(severity=Severity(2, Reversibility.IRREVERSIBLE))
    assert approval_requirement(irreversible, tier=2, gate=evaluate_gates(irreversible)) == "HUMAN"

    assert approval_requirement(ok_op, tier=0, gate=gate) == "BLOCKED"  # lockout

# ------------------------------------------------------------ e2e heartbeat

def test_e2e_governed_loop():
    factory = make_session_factory(make_engine("sqlite://"))
    mainmod.SessionFactory = factory  # point the app at a fresh in-memory DB
    client = TestClient(mainmod.app)

    r = client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-Id": tid}

    r = client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please", "tier": 1})
    card = r.json()["cards"][0]
    assert card["state"] == "AWAITING_APPROVAL"
    assert "cloud_dns zone woktok.in" in card["preview"]
    assert card["cost_estimate"] == "2500.00 INR/mo"

    r = client.post(f"/ops/{card['op_id']}/decision", headers=H,
                    json={"decision": "approve", "actor": "chandan", "surface": "whatsapp"})
    assert r.json()["state"] == "DONE"

    r = client.get(f"/ops/{card['op_id']}", headers=H)
    kinds = [t["kind"] for t in r.json()["trace"]]
    assert kinds.count("transition") >= 6  # the full loop left footprints

    assert client.get("/audit/verify").json()["ok"] is True

    # cross-tenant access is structurally denied
    r = client.get(f"/ops/{card['op_id']}", headers={"X-Tenant-Id": "someone-else"})
    assert r.status_code == 404


def test_e2e_blocked_op_explains_itself():
    factory = make_session_factory(make_engine("sqlite://"))
    mainmod.SessionFactory = factory
    client = TestClient(mainmod.app)
    r = client.post("/tenants", json={"name": "T", "brand_name": "B"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]

    # Force a too-expensive plan through the demo adapter by proposing directly
    factory2 = mainmod.SessionFactory
    s = factory2()
    spec = _spec(tenant_id=tid, brand_id=bid, cost_estimate=Money(2_000_000))
    row = loop.propose(s, spec, actor="test")
    gate, requirement = loop.preview_and_gate(s, row, tier=2)
    s.commit()
    assert requirement == "BLOCKED" and row.state == "BLOCKED"
    assert gate.violations[0].message  # never a generic error
    s.close()
