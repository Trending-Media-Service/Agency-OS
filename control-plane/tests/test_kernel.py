"""Kernel tests. The e2e test at the bottom is the Slice 1 heartbeat:
intent -> preview -> gate -> approval -> outbox -> execute -> verify -> DONE,
with the audit chain intact.
"""
import datetime as dt
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
import tempfile
import pathlib
import shutil

import app.main as mainmod
from app.database import get_db, get_worker_db, get_worker_session_maker
from app.kernel import loop
from app.kernel.optypes import (InvalidTransition, Money, OpSpec, OpState,
                                Reversibility, Severity, assert_transition)
from app.kernel.services import (audit_append, audit_verify, evaluate_gates,
                                 approval_requirement, saturating_penalty,
                                 tier_for, trust_score)
from app.models import AuditEvent, Base, OpRow, OutboxItem, TrustSnapshot, OpTrace

NOW = dt.datetime(2026, 6, 10, tzinfo=dt.timezone.utc)








def _spec(**kw) -> OpSpec:
    base = dict(tenant_id="t1", brand_id="b1", domain="provision",
                action="provision.web_host.create",
                params={"domain": "x.in", "recipe": "web-host", "version": "0.1.0"},
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

async def test_audit_chain_verifies_and_detects_tamper(session: AsyncSession):
    for i in range(5):
        await audit_append(session, tenant_id="t1", actor="test", action=f"e{i}")
    await session.flush()
    assert await audit_verify(session) == (True, None)

    result = await session.execute(select(AuditEvent).filter_by(action="e2"))
    victim = result.scalars().one()
    victim.payload = {"injected": True}  # tamper
    await session.flush()
    ok, first_bad = await audit_verify(session)
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

async def test_e2e_governed_loop(client, db_engine):
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please"})
    card = r.json()["cards"][0]
    assert card["state"] == "AWAITING_APPROVAL"
    assert "cloud_dns zone woktok.in" in card["preview"]
    assert card["cost_estimate"] == "2500.00 INR/mo"

    r = await client.post(f"/ops/{card['op_id']}/decision", headers=H,
                    json={"decision": "approve", "actor": "chandan", "surface": "whatsapp"})
    assert r.json()["state"] == "APPROVED"

    r = await client.get(f"/ops/{card['op_id']}", headers=H)
    assert r.json()["state"] == "DONE"
    kinds = [t["kind"] for t in r.json()["trace"]]
    assert kinds.count("transition") >= 6

    r = await client.get("/audit/verify")
    assert r.json()["ok"] is True

    # cross-tenant access is structurally denied
    r = await client.get(f"/ops/{card['op_id']}", headers={"X-Tenant-ID": "someone-else"})
    assert r.status_code == 404


async def test_e2e_blocked_op_explains_itself(db_engine, client):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        r = await client.post("/tenants", json={"name": "T", "brand_name": "B"})
        tid, bid = r.json()["tenant_id"], r.json()["brand_id"]

        spec = _spec(tenant_id=tid, brand_id=bid, cost_estimate=Money(2_000_000))
        row = await loop.propose(s, spec, actor="test")
        gate, requirement = await loop.preview_and_gate(s, row, tier=2)
        await s.commit()
        assert requirement == "BLOCKED" and row.state == "BLOCKED"
        assert gate.violations[0].message


async def test_drain_outbox_endpoint_returns_ok(client):
    r = await client.post("/tasks/drain-outbox")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "processed_items" in r.json()


# ------------------------------------------------------------ WhatsApp Webhook Tests

async def test_whatsapp_webhook_verification(client):
    # Setup verify token
    mainmod.WHATSAPP_VERIFY_TOKEN = "meaty"

    # Correct token
    r = await client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=1234&hub.verify_token=meaty")
    assert r.status_code == 200
    assert r.text == "1234"

    # Incorrect token
    r = await client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=1234&hub.verify_token=wrong")
    assert r.status_code == 403


@patch("app.whatsapp.httpx.AsyncClient")
async def test_whatsapp_e2e_approval_flow(mock_client_class, client, db_engine):
    # Setup WhatsApp mock config
    import app.whatsapp as wa
    wa.WHATSAPP_TOKEN = "mock_token"
    wa.WHATSAPP_PHONE_NUMBER_ID = "12345"
    wa.WHATSAPP_APPROVER_PHONE = "919999999999"
    wa.WHATSAPP_TEMPLATE_NAME = "agency_os_approval"

    # Mock AsyncClient context manager and its post method
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"messages": [{"id": "mock_wamid_approval"}]}
    mock_client.post.return_value = mock_response

    # 1. Propose Op (Submit intent)
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    # Submit intent that requires approval (tier 1)
    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please"})
    card = r.json()["cards"][0]
    op_id = card["op_id"]
    assert card["state"] == "AWAITING_APPROVAL"

    # Wait for background task to send whatsapp card
    assert mock_client.post.called
    # Check that it sent the correct payload
    args, kwargs = mock_client.post.call_args
    assert "12345" in args[0] # Phone Number ID
    payload = kwargs["json"]
    assert payload["to"] == "919999999999"
    assert payload["template"]["name"] == "agency_os_approval"
    # Verify button payloads
    components = payload["template"]["components"]
    button_0 = next(c for c in components if c["type"] == "button" and c["index"] == "0")
    assert button_0["parameters"][0]["payload"] == f"approve_{op_id}"

    # 2. Simulate User clicking "Approve" via Webhook
    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "msg_id_1",
                                    "type": "button",
                                    "button": {
                                        "payload": f"approve_{op_id}",
                                        "text": "Approve"
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    # Call the webhook (POST)
    r = await client.post("/webhooks/whatsapp", json=webhook_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    # 3. Verify Op is transitioned to DONE
    r = await client.get(f"/ops/{op_id}", headers=H)
    assert r.json()["state"] == "DONE"


@patch("app.whatsapp.httpx.AsyncClient")
async def test_whatsapp_e2e_rejection_flow(mock_client_class, client, db_engine):
    # Setup WhatsApp mock config
    import app.whatsapp as wa
    wa.WHATSAPP_TOKEN = "mock_token"
    wa.WHATSAPP_PHONE_NUMBER_ID = "12345"
    wa.WHATSAPP_APPROVER_PHONE = "919999999999"

    # Mock AsyncClient
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"messages": [{"id": "mock_wamid_rejection"}]}
    mock_client.post.return_value = mock_response

    # Propose Op
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}
    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please"})
    op_id = r.json()["cards"][0]["op_id"]

    # Simulate User clicking "Reject" via Webhook
    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "msg_id_2",
                                    "type": "button",
                                    "button": {
                                        "payload": f"reject_{op_id}",
                                        "text": "Reject"
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    r = await client.post("/webhooks/whatsapp", json=webhook_payload)
    assert r.status_code == 200

    # Verify Op is transitioned to REJECTED
    r = await client.get(f"/ops/{op_id}", headers=H)
    assert r.json()["state"] == "REJECTED"


@patch("app.whatsapp.httpx.AsyncClient")
async def test_whatsapp_e2e_modify_flow(mock_client_class, client, db_engine):
    # Setup WhatsApp mock config
    import app.whatsapp as wa
    wa.WHATSAPP_TOKEN = "mock_token"
    wa.WHATSAPP_PHONE_NUMBER_ID = "12345"
    wa.WHATSAPP_APPROVER_PHONE = "919999999999"

    # Mock AsyncClient
    mock_client = AsyncMock()
    mock_client_class.return_value.__aenter__.return_value = mock_client
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"messages": [{"id": "mock_wamid_modify"}]}
    mock_client.post.return_value = mock_response

    # Propose Op
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}
    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please"})
    op_id = r.json()["cards"][0]["op_id"]

    # Simulate User sending text message "modify make it 40k"
    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "msg_id_3",
                                    "type": "text",
                                    "text": {
                                        "body": "modify use woktok.co"
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    r = await client.post("/webhooks/whatsapp", json=webhook_payload)
    assert r.status_code == 200

    # Verify Op is re-gated and transitioned back to AWAITING_APPROVAL with updated params
    r = await client.get(f"/ops/{op_id}", headers=H)
    assert r.json()["state"] == "AWAITING_APPROVAL"
    assert r.json()["params"]["domain"] == "woktok.co"

    # Verify that the modify approval is in the traces
    traces = r.json()["trace"]
    assert len(traces) >= 2

    # Verify that mock_client.post was called twice (initial + modified card)
    assert mock_client.post.call_count == 2
    args, kwargs = mock_client.post.call_args_list[1]
    payload = kwargs["json"]
    # Check that the second card references the modified domain
    assert "woktok.co" in str(payload)


# ------------------------------------------------------------- trust engine E2E

async def test_e2e_trust_tier_2_auto_approves(client, db_engine):
    from app.models import TrustSnapshot

    # 1. Create tenant/brand
    r = await client.post("/tenants", json={"name": "TrustBrand", "brand_name": "Trusty"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    # 2. Insert a TrustSnapshot with tier=2 for this brand and domain "provision"
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="provision", score=90.0, tier=2))
        await s.commit()

    # 3. Submit intent (no tier parameter)
    r = await client.post("/intents", headers=H,
                          json={"brand_id": bid, "text": "host woktok.in please"})
    card = r.json()["cards"][0]
    assert card["state"] == "APPROVED"
    assert card["requirement"] == "AUTO"


async def test_trust_snapshots_nightly_job(db_engine):
    from app.kernel.services import compute_snapshots
    from app.models import Tenant, Brand, TrustEvent, TrustSnapshot

    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        # Create brand
        t = Tenant(name="T")
        s.add(t)
        await s.flush()
        b = Brand(tenant_id=t.id, name="B")
        s.add(b)
        await s.flush()

        # Add some trust events
        s.add(TrustEvent(tenant_id=t.id, brand_id=b.id, domain="provision", kind="verified_success", base_delta=1.0))
        s.add(TrustEvent(tenant_id=t.id, brand_id=b.id, domain="provision", kind="verify_failure", base_delta=-8.0))
        await s.commit()

    async with async_session() as s:
        await compute_snapshots(s)
        await s.commit()

    async with async_session() as s:
        res = await s.execute(select(TrustSnapshot).where(TrustSnapshot.brand_id == b.id, TrustSnapshot.domain == "provision"))
        snap = res.scalar_one()
        # Initial health score = 70.0 (gtm + pixel + capi) (Wait: in services.py it is 67.0! Check math below)
        # score = health (67.0) - penalties (0) + history (-7) = 60.0
        # Tier = 1
        assert snap.score == pytest.approx(60.0)
        assert snap.tier == 1


async def test_decide_enforces_override_reason(db_engine):
    from app.kernel import loop
    from app.models import OpRow, TrustEvent
    from app.kernel.optypes import Severity, Reversibility, Money
    from app.kernel.services import evaluate_gates

    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        # Create an Op that violates cost ceiling policy
        # Cost ceiling is 10,000 INR (1,000,000 minor)
        spec = _spec(cost_estimate=Money(2_000_000))  # 20,000 INR -> violates cost ceiling!
        row = await loop.propose(s, spec, actor="test")
        await s.commit()

    async with async_session() as s:
        db_row = await s.get(OpRow, row.id)
        # Move to AWAITING_APPROVAL state
        db_row.state = "AWAITING_APPROVAL"
        await s.commit()

    async with async_session() as s:
        db_row = await s.get(OpRow, row.id)
        # Try to approve without reason -> should fail
        with pytest.raises(ValueError, match="Override reason is mandatory"):
            await loop.decide(s, db_row, decision="approve", actor="chandan", role="owner", surface="whatsapp")

        # Try to approve with reason -> should succeed
        await loop.decide(s, db_row, decision="approve", actor="chandan", role="owner", surface="whatsapp", reason="Approved for client launch")
        await s.commit()

    async with async_session() as s:
        # Check that TrustEvent of kind 'override' was written
        res = await s.execute(select(TrustEvent).where(TrustEvent.brand_id == "b1", TrustEvent.kind == "override"))
        ev = res.scalar_one()
        assert ev.base_delta == -5.0
        assert ev.reason == "Approved for client launch"


@pytest.mark.asyncio
async def test_e2e_brand_bootstrap_saga(client, db_engine):
    # Setup: Create initial trust snapshot for b1/provision so we don't fail tier resolution
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id="t1", brand_id="b1", domain="provision", tier=1, score=75.0))
        await s.commit()

    H = {"X-Tenant-ID": "t1"}
    # 1. Submit brand bootstrap intent
    resp = await client.post("/intents", headers=H, json={
        "domain": "provision",
        "brand_id": "b1",
        "text": "bootstrap brand ableys ableys.com"
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Only the parent card should be returned!
    assert len(data["cards"]) == 1
    parent_card = data["cards"][0]
    assert parent_card["action"] == "provision.brand_bootstrap.create"
    assert parent_card["state"] == "AWAITING_APPROVAL"
    parent_id = parent_card["op_id"]

    # Verify database state for children
    async with async_session() as s:
        # Parent
        parent_row = await s.get(OpRow, parent_id)
        assert parent_row is not None
        assert parent_row.state == "AWAITING_APPROVAL"

        # Children
        res = await s.execute(select(OpRow).where(OpRow.parent_op_id == parent_id).order_by(OpRow.sequence_order))
        children = res.scalars().all()
        assert len(children) == 2

        child_baseline, child_web = children[0], children[1]
        assert child_baseline.action == "provision.brand_baseline.create"
        assert child_baseline.sequence_order == 1
        assert child_baseline.state == "AWAITING_APPROVAL"

        assert child_web.action == "provision.web_host.create"
        assert child_web.sequence_order == 2
        assert child_web.state == "AWAITING_APPROVAL"

    # 2. Approve the parent Op (triggers child_baseline execution automatically)
    resp_dec = await client.post(f"/ops/{parent_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_dec.status_code == 200, resp_dec.text

    # Verify parent is EXECUTING, child_baseline is DONE, and child_web is APPROVED and enqueued
    async with async_session() as s:
        parent_row = await s.get(OpRow, parent_id)
        assert parent_row.state == "EXECUTING"

        res = await s.execute(select(OpRow).where(OpRow.parent_op_id == parent_id).order_by(OpRow.sequence_order))
        children = res.scalars().all()
        child_baseline, child_web = children[0], children[1]
        assert child_baseline.state == "DONE"
        assert child_web.state == "APPROVED"

        # Check Outbox
        res_outbox = await s.execute(select(OutboxItem).where(OutboxItem.status == "PENDING"))
        outbox_items = res_outbox.scalars().all()
        # Should contain child_web!
        assert len(outbox_items) == 1
        assert outbox_items[0].op_id == child_web.id

    # 3. Drain outbox (executes child_web)
    async with async_session() as s:
        processed = await loop.drain_once(s)
        assert processed == 1
        await s.commit()

    # Verify both children and parent are DONE
    async with async_session() as s:


        child_baseline = await s.get(OpRow, child_baseline.id)
        assert child_baseline.state == "DONE"

        child_web = await s.get(OpRow, child_web.id)
        assert child_web.state == "DONE"

        parent_row = await s.get(OpRow, parent_id)
        assert parent_row.state == "DONE"


@pytest.mark.asyncio
async def test_e2e_brand_bootstrap_saga_rollback(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id="t1", brand_id="b2", domain="provision", tier=1, score=75.0))
        await s.commit()

    H = {"X-Tenant-ID": "t1"}
    # 1. Submit brand bootstrap intent with fail.in domain to trigger child_web execute failure
    resp = await client.post("/intents", headers=H, json={
        "domain": "provision",
        "brand_id": "b2",
        "text": "bootstrap brand fail fail.in" 
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    parent_id = data["cards"][0]["op_id"]

    # 2. Approve parent Op (triggers child_baseline execution -> DONE)
    resp_dec = await client.post(f"/ops/{parent_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_dec.status_code == 200

    # Verify child_baseline is DONE, parent is EXECUTING, and child_web is APPROVED and enqueued
    async with async_session() as s:
        res = await s.execute(select(OpRow).where(OpRow.parent_op_id == parent_id).order_by(OpRow.sequence_order))
        children = res.scalars().all()
        child_baseline, child_web = children[0], children[1]
        assert child_baseline.state == "DONE"
        assert child_web.state == "APPROVED"

        parent_row = await s.get(OpRow, parent_id)
        assert parent_row.state == "EXECUTING"

        res_outbox = await s.execute(select(OutboxItem).where(OutboxItem.status == "PENDING"))
        assert len(res_outbox.scalars().all()) == 1

    # 3. Drain outbox (executes child_web -> fails, triggers cascading rollback)
    async with async_session() as s:
        processed = await loop.drain_once(s)
        assert processed == 1
        await s.commit()

    # Verify states: all children and parent are ROLLED_BACK
    async with async_session() as s:


        res = await s.execute(select(OpRow).where(OpRow.parent_op_id == parent_id).order_by(OpRow.sequence_order))
        children = res.scalars().all()
        child_baseline, child_web = children[0], children[1]

        assert child_web.state == "ROLLED_BACK"
        assert child_baseline.state == "ROLLED_BACK"

        parent_row = await s.get(OpRow, parent_id)
        assert parent_row.state == "ROLLED_BACK"


@pytest.mark.asyncio
async def test_cost_ledger_ingestion_and_rollups(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Create a trust snapshot to pass gate tier resolution
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id="t1", brand_id="b1", domain="provision", tier=1, score=75.0))
        await s.commit()

    H = {"X-Tenant-ID": "t1"}

    # 2. Submit intent (which will log simulated gemini planning tokens cost)
    resp = await client.post("/intents", headers=H, json={
        "domain": "provision",
        "brand_id": "b1",
        "text": "host my site ableys.com"
    })
    assert resp.status_code == 200
    data = resp.json()
    op_id = data["cards"][0]["op_id"]

    # Verify that planning cost (llm_tokens) was logged and attributed to the Op ID
    async with async_session() as s:
        from app.kernel.services import get_tenant_cost_rollup, get_op_cost_total
        op_total = await get_op_cost_total(s, op_id)
        assert op_total == 57  # planning cost: 57 paise

        tenant_rollup = await get_tenant_cost_rollup(s, "t1")
        assert tenant_rollup.get("llm_tokens") == 57

    # 3. Approve the Op to execute it
    resp_dec = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_dec.status_code == 200

    # 4. Ingest GCP billing record for this tenant (simulating GCP cost ledger ingestion)
    async with async_session() as s:
        from app.kernel.services import ingest_gcp_billing
        await ingest_gcp_billing(
            s,
            tenant_id="t1",
            resource_id="run-service-web-ableys-com",
            amount_minor=1240,  # 12.40 INR
            currency="INR",
            labels={"tenant_id": "t1", "op_id": op_id}
        )
        await s.commit()

    # 5. Verify the updated tenant rollup and total costs
    async with async_session() as s:
        tenant_rollup = await get_tenant_cost_rollup(s, "t1")
        assert tenant_rollup.get("llm_tokens") == 57
        assert tenant_rollup.get("gcp_resource") == 1240



    # 6. Verify that execution costs were recorded
    async with async_session() as s:
        # After execution, child Op should return:
        # - zone_register: 2000 paise (20 INR)
        # - service_account_create: 150 paise (1.50 INR)
        # Total execution cost = 2150 paise
        op_total = await get_op_cost_total(s, op_id)
        # Total cost for op_id should be planning (57) + execution (2150) = 2207 paise
        assert op_total == 2207

        tenant_rollup = await get_tenant_cost_rollup(s, "t1")
        assert tenant_rollup.get("llm_tokens") == 57
        assert tenant_rollup.get("api_call") == 2150
        assert tenant_rollup.get("gcp_resource") == 1240


@pytest.mark.asyncio
async def test_observability_and_trace_propagation(client, db_engine, capsys):
    import json
    import logging
    from app.observability import setup_logging, trace_context
    from app.database import tenant_context

    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Create a trust snapshot to pass gate tier resolution
    async with async_session() as s:
        s.add(TrustSnapshot(tenant_id="t1", brand_id="b1", domain="provision", tier=1, score=75.0))
        await s.commit()

    # 2. Test JSON formatted logging directly
    setup_logging(level="INFO", json_format=True)
    
    test_logger = logging.getLogger("test_obs")
    
    # Set context variables manually to simulate a request flow
    t_token = tenant_context.set("t1")
    tr_token = trace_context.set("tr-manual-999")
    try:
        test_logger.info("Structured log statement", extra={"custom_metric": 42})
    finally:
        tenant_context.reset(t_token)
        trace_context.reset(tr_token)
        
    # Reset logging back to text format so we don't mess up standard pytest logs
    setup_logging(level="INFO", json_format=False)
    
    # Capture stderr and verify JSON formatting (StreamHandler outputs to stderr by default)
    captured = capsys.readouterr()
    log_line = captured.err.strip()
    
    # Parse the captured log statement as JSON
    parsed = json.loads(log_line)
    assert parsed["message"] == "Structured log statement"
    assert parsed["severity"] == "INFO"
    assert parsed["logger"] == "test_obs"
    assert parsed["trace_id"] == "tr-manual-999"
    assert parsed["tenant_id"] == "t1"
    assert parsed["custom_metric"] == 42
    
    # 3. Test HTTP propagation via TraceMiddleware
    H = {"X-Tenant-ID": "t1", "X-Trace-ID": "tr-http-555"}
    resp = await client.post("/intents", headers=H, json={
        "domain": "provision",
        "brand_id": "b1",
        "text": "host my site ableys.com"
    })
    assert resp.status_code == 200
    assert resp.headers.get("X-Trace-ID") == "tr-http-555"
    data = resp.json()
    op_id = data["cards"][0]["op_id"]
    
    # 4. Approve the Op (triggers execution and outbox enqueuing)
    resp_dec = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_dec.status_code == 200
    
    # 5. Verify that OutboxItem in database contains the correct propagated trace ID
    async with async_session() as s:
        res_outbox = await s.execute(select(OutboxItem).where(OutboxItem.op_id == op_id))
        outbox_item = res_outbox.scalar_one()
        assert outbox_item.trace_id == "tr-http-555"


@pytest.mark.asyncio
async def test_recipe_promotion_endpoint(client):
    import shutil
    
    # 1. Setup mock experimental recipe folder
    RECIPES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../recipes"))
    exp_path = os.path.join(RECIPES_ROOT, "experimental", "test-promo", "0.1.0")
    prod_path = os.path.join(RECIPES_ROOT, "test-promo", "0.1.0")
    
    os.makedirs(exp_path, exist_ok=True)
    with open(os.path.join(exp_path, "recipe.yaml"), "w") as f:
        f.write("name: test-promo\nversion: 0.1.0")
    with open(os.path.join(exp_path, "main.tf"), "w") as f:
        f.write("output \"test\" { value = 1 }")
        
    try:
        # 2. Execute promotion
        H = {"X-Tenant-Id": "t1"}
        r = await client.post("/recipes/promote", headers=H, json={"recipe_name": "test-promo"})
        assert r.status_code == 200, f"Promo failed: {r.status_code} - {r.text}"
        data = r.json()
        assert data["status"] == "promoted"
        assert data["recipe_name"] == "test-promo"
        
        # 3. Assert files copied
        assert os.path.exists(os.path.join(prod_path, "recipe.yaml"))
        assert os.path.exists(os.path.join(prod_path, "main.tf"))
        
        # 4. Assert 404 for non-existent recipe promotion
        r_404 = await client.post("/recipes/promote", headers=H, json={"recipe_name": "missing-recipe"})
        assert r_404.status_code == 404
        
        # 5. Assert 400 for missing file promotion
        exp_bad = os.path.join(RECIPES_ROOT, "experimental", "test-promo-bad", "0.1.0")
        os.makedirs(exp_bad, exist_ok=True)
        with open(os.path.join(exp_bad, "recipe.yaml"), "w") as f:
            f.write("bad recipe")
        r_400 = await client.post("/recipes/promote", headers=H, json={"recipe_name": "test-promo-bad"})
        assert r_400.status_code == 400
        
    finally:
        # Cleanup mock folders
        shutil.rmtree(os.path.join(RECIPES_ROOT, "experimental", "test-promo"), ignore_errors=True)
        shutil.rmtree(os.path.join(RECIPES_ROOT, "experimental", "test-promo-bad"), ignore_errors=True)
        shutil.rmtree(os.path.join(RECIPES_ROOT, "test-promo"), ignore_errors=True)





