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
from app.models import AuditEvent, Base

NOW = dt.datetime(2026, 6, 10, tzinfo=dt.timezone.utc)





@pytest.fixture()
async def db_file():
    temp_dir = tempfile.mkdtemp()
    db_path = pathlib.Path(temp_dir) / "test.db"
    yield f"sqlite+aiosqlite:///{db_path}"
    shutil.rmtree(temp_dir)


@pytest.fixture()
async def db_engine(db_file):
    engine = create_async_engine(db_file)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as s:
        yield s


@pytest.fixture()
async def client(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db():
        async with async_session() as s:
            await s.begin()
            try:
                yield s
                if s.in_transaction():
                    await s.commit()
            except Exception:
                if s.in_transaction():
                    await s.rollback()
                raise

    def override_get_worker_session_maker():
        return async_session

    mainmod.app.dependency_overrides[get_db] = override_get_db
    mainmod.app.dependency_overrides[get_worker_db] = override_get_db
    mainmod.app.dependency_overrides[get_worker_session_maker] = override_get_worker_session_maker
    async with AsyncClient(transport=ASGITransport(app=mainmod.app), base_url="http://test") as ac:
        yield ac
    mainmod.app.dependency_overrides.clear()


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
                    json={"brand_id": bid, "text": "host woktok.in please", "tier": 1})
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
    mock_client.post.return_value = mock_response

    # 1. Propose Op (Submit intent)
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}

    # Submit intent that requires approval (tier 1)
    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please", "tier": 1})
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
    mock_client.post.return_value = mock_response

    # Propose Op
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}
    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please", "tier": 1})
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
    mock_client.post.return_value = mock_response

    # Propose Op
    r = await client.post("/tenants", json={"name": "Tanmatra", "brand_name": "Wok-Tok"})
    tid, bid = r.json()["tenant_id"], r.json()["brand_id"]
    H = {"X-Tenant-ID": tid}
    r = await client.post("/intents", headers=H,
                    json={"brand_id": bid, "text": "host woktok.in please", "tier": 1})
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
                                        "body": "modify make it 40k"
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

    # Verify Op is transitioned back to PREVIEWED
    r = await client.get(f"/ops/{op_id}", headers=H)
    assert r.json()["state"] == "PREVIEWED"

    # Verify that the modify approval is in the traces
    traces = r.json()["trace"]
    assert len(traces) >= 2
