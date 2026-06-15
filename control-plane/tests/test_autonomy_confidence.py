import pytest
from sqlalchemy import select
from app.models import OpRow, TrustSnapshot, ShadowDecision
from unittest.mock import patch

@pytest.mark.asyncio
async def test_shadow_decision_recorded_on_approve(client, session):
    # 1. Setup tenant and brand
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert resp.status_code == 200
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]

    # Initialize trust snapshot to Tier 1 (score 65.0) to force human approval
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="grow", score=65.0, tier=1))
    await session.commit()

    H = {"X-Tenant-Id": tid}

    # 2. Propose grow.campaign.pause (HUMAN in Tier 1, AUTO in Tier 2)
    resp_intent = await client.post("/intents", headers=H, json={
        "domain": "grow",
        "brand_id": bid,
        "text": "pause campaign camp-1"
    })
    assert resp_intent.status_code == 200
    intent_data = resp_intent.json()
    assert len(intent_data["cards"]) == 1
    op_card = intent_data["cards"][0]
    assert op_card["state"] == "AWAITING_APPROVAL"
    op_id = op_card["op_id"]

    # 3. Human approves it
    resp_app = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "web"
    })
    assert resp_app.status_code == 200
    assert resp_app.json()["state"] == "APPROVED"

    # 4. Verify shadow decision is recorded
    session.expire_all() # Clear cache to get fresh data from API commit
    stmt = select(ShadowDecision).where(ShadowDecision.op_id == op_id)
    res = await session.execute(stmt)
    shadow = res.scalar_one_or_none()
    assert shadow is not None
    assert shadow.tenant_id == tid
    assert shadow.human_decision == "approve"
    assert shadow.shadow_tier == 2
    assert shadow.shadow_requirement == "AUTO"
    assert shadow.agreed is True


@pytest.mark.asyncio
async def test_shadow_decision_recorded_on_reject_critical_disagreement(client, session):
    # Setup
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="grow", score=65.0, tier=1))
    await session.commit()
    H = {"X-Tenant-Id": tid}

    # Propose grow.campaign.pause (HUMAN in Tier 1, AUTO in Tier 2)
    resp_intent = await client.post("/intents", headers=H, json={
        "domain": "grow",
        "brand_id": bid,
        "text": "pause campaign camp-2"
    })
    op_card = resp_intent.json()["cards"][0]
    assert op_card["state"] == "AWAITING_APPROVAL"
    op_id = op_card["op_id"]

    # Human REJECTS it
    resp_app = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "reject",
        "actor": "chandan",
        "role": "owner",
        "surface": "web",
        "reason": "unnecessary pause"
    })
    assert resp_app.status_code == 200
    assert resp_app.json()["state"] == "REJECTED"

    # Verify shadow decision
    session.expire_all()
    stmt = select(ShadowDecision).where(ShadowDecision.op_id == op_id)
    res = await session.execute(stmt)
    shadow = res.scalar_one_or_none()
    assert shadow is not None
    assert shadow.human_decision == "reject"
    assert shadow.shadow_requirement == "AUTO"
    assert shadow.agreed is False

    # Verify GET /autonomy-confidence
    resp_metrics = await client.get(f"/autonomy-confidence?brand_id={bid}&domain=grow", headers=H)
    assert resp_metrics.status_code == 200
    metrics = resp_metrics.json()
    assert metrics["total_decisions"] == 1
    assert metrics["agreement_rate"] == 0.0
    assert metrics["critical_disagreements"] == 1
    assert metrics["recommendation"] == "OBSERVE"


@pytest.mark.asyncio
async def test_shadow_decision_human_requirement(client, session):
    # Setup tenant and brand
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="grow", score=65.0, tier=1))
    
    # Manually insert a STATUTORY op in AWAITING_APPROVAL state
    op = OpRow(
        id="op_statutory_123",
        tenant_id=tid,
        brand_id=bid,
        domain="grow",
        action="grow.campaign.create",
        state="AWAITING_APPROVAL",
        impact=1,
        reversibility="COMPENSATABLE",
        statutory=True, # Trigger statutory_firewall
        idem_key="idem_statutory_123"
    )
    session.add(op)
    await session.commit()
    
    H = {"X-Tenant-Id": tid}
    
    # Human approves it (with override reason)
    resp_app = await client.post(f"/ops/op_statutory_123/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "web",
        "reason": "statutory override"
    })
    assert resp_app.status_code == 200
    assert resp_app.json()["state"] == "APPROVED"
    
    # Verify shadow decision
    session.expire_all()
    stmt = select(ShadowDecision).where(ShadowDecision.op_id == "op_statutory_123")
    res = await session.execute(stmt)
    shadow = res.scalar_one_or_none()
    assert shadow is not None
    assert shadow.shadow_requirement == "HUMAN"
    assert shadow.agreed is True


@pytest.mark.asyncio
async def test_no_shadow_if_already_tier2(client, session):
    # Setup tenant and brand
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]
    
    # Initialize to Tier 2
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="grow", score=90.0, tier=2))
    
    # Manually insert an op in AWAITING_APPROVAL state
    op = OpRow(
        id="op_tier2_human_123",
        tenant_id=tid,
        brand_id=bid,
        domain="grow",
        action="grow.campaign.create",
        state="AWAITING_APPROVAL",
        impact=1,
        reversibility="COMPENSATABLE",
        statutory=True,
        idem_key="idem_tier2_human_123"
    )
    session.add(op)
    await session.commit()
    
    H = {"X-Tenant-Id": tid}
    
    # Human approves it
    resp_app = await client.post(f"/ops/op_tier2_human_123/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "web",
        "reason": "statutory override"
    })
    assert resp_app.status_code == 200
    
    # Verify NO shadow decision is recorded
    session.expire_all()
    stmt = select(ShadowDecision).where(ShadowDecision.op_id == "op_tier2_human_123")
    res = await session.execute(stmt)
    shadow = res.scalar_one_or_none()
    assert shadow is None


@pytest.mark.asyncio
async def test_shadow_failure_swallowed(client, session):
    # Setup
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]
    session.add(TrustSnapshot(tenant_id=tid, brand_id=bid, domain="grow", score=65.0, tier=1))
    
    op = OpRow(
        id="op_fail_123",
        tenant_id=tid,
        brand_id=bid,
        domain="grow",
        action="grow.campaign.pause", # Use pause instead of alert to be safe, though manual insert bypasses planning
        state="AWAITING_APPROVAL",
        impact=1,
        reversibility="COMPENSATABLE",
        idem_key="idem_fail_123"
    )
    session.add(op)
    await session.commit()
    
    H = {"X-Tenant-Id": tid}
    
    # Mock _record_shadow_decision to raise an exception
    with patch("app.kernel.loop._record_shadow_decision", side_effect=RuntimeError("Simulated shadow failure")):
        resp_app = await client.post(f"/ops/op_fail_123/decision", headers=H, json={
            "decision": "approve",
            "actor": "chandan",
            "role": "owner",
            "surface": "web"
        })
        assert resp_app.status_code == 200
        assert resp_app.json()["state"] == "APPROVED"
        
    # Verify the op was indeed approved (or has progressed to DONE) in DB
    session.expire_all()
    stmt = select(OpRow).where(OpRow.id == "op_fail_123")
    res = await session.execute(stmt)
    row = res.scalar_one()
    assert row.state in ("APPROVED", "DONE")
