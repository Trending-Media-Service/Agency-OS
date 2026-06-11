import pytest
from sqlalchemy import select
from app.models import OpRow, TrustSnapshot, TrustEvent
from app.services.marketing import MockMarketingClient

@pytest.fixture(autouse=True)
def clear_marketing_client():
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()

@pytest.mark.asyncio
async def test_trust_evaluation_success_roi(client, session):
    # 1. Setup tenant and brand
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert resp.status_code == 200
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]

    # 2. Setup mock campaign in marketing client (positive ROI 1.5)
    campaign_id = f"camp-{bid}-summersale"
    m_client = MockMarketingClient()
    await m_client.create_campaign(campaign_id, "summersale", 1000000, 15000)

    # 3. Insert a successful campaign create Op in DB
    op = OpRow(
        id="op-create-1",
        tenant_id=tid,
        brand_id=bid,
        domain="grow",
        action="grow.campaign.create",
        state="DONE",
        params={"campaign_id": campaign_id, "name": "summersale", "budget_minor": 1000000},
        impact=2,
        reversibility="COMPENSATABLE",
        idem_key="idem_grow_1"
    )
    session.add(op)
    await session.commit()

    # 4. Trigger trust evaluation task
    resp_eval = await client.post("/tasks/evaluate-trust")
    assert resp_eval.status_code == 200
    eval_data = resp_eval.json()
    assert eval_data["events_added"] == 1

    # 5. Verify database state
    # Should have a new TrustEvent
    stmt_ev = select(TrustEvent).where(TrustEvent.tenant_id == tid, TrustEvent.brand_id == bid, TrustEvent.domain == "grow")
    res_ev = await session.execute(stmt_ev)
    events = res_ev.scalars().all()
    assert len(events) == 1
    assert events[0].kind == "verified_success"
    assert events[0].base_delta == 5.0

    # Should have a new TrustSnapshot (baseline 67.0 + 1.0 = 68.0, Tier 1)
    stmt_snap = select(TrustSnapshot).where(TrustSnapshot.tenant_id == tid, TrustSnapshot.brand_id == bid, TrustSnapshot.domain == "grow").order_by(TrustSnapshot.ts.desc())
    res_snap = await session.execute(stmt_snap)
    snapshots = res_snap.scalars().all()
    assert len(snapshots) == 1
    latest_snap = snapshots[0]
    assert pytest.approx(latest_snap.score, abs=0.1) == 68.0
    assert latest_snap.tier == 1


@pytest.mark.asyncio
async def test_trust_evaluation_poor_roi(client, session):
    # 1. Setup tenant and brand
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert resp.status_code == 200
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]

    # 2. Setup mock campaign in marketing client (poor ROI 0.5 because name contains "fail")
    campaign_id = f"camp-{bid}-failcampaign"
    m_client = MockMarketingClient()
    await m_client.create_campaign(campaign_id, "failcampaign", 1000000, 15000)

    # 3. Insert a successful campaign create Op in DB
    op = OpRow(
        id="op-create-2",
        tenant_id=tid,
        brand_id=bid,
        domain="grow",
        action="grow.campaign.create",
        state="DONE",
        params={"campaign_id": campaign_id, "name": "failcampaign", "budget_minor": 1000000},
        impact=2,
        reversibility="COMPENSATABLE",
        idem_key="idem_grow_2"
    )
    session.add(op)
    await session.commit()

    # 4. Trigger trust evaluation task
    resp_eval = await client.post("/tasks/evaluate-trust")
    assert resp_eval.status_code == 200
    eval_data = resp_eval.json()
    assert eval_data["events_added"] == 1

    # 5. Verify database state
    # Should have a new TrustEvent with verify_failure
    stmt_ev = select(TrustEvent).where(TrustEvent.tenant_id == tid, TrustEvent.brand_id == bid, TrustEvent.domain == "grow")
    res_ev = await session.execute(stmt_ev)
    events = res_ev.scalars().all()
    assert len(events) == 1
    assert events[0].kind == "verify_failure"
    assert events[0].base_delta == -10.0

    # Should have a new TrustSnapshot (baseline 67.0 - 8.0 = 59.0, Tier 0)
    stmt_snap = select(TrustSnapshot).where(TrustSnapshot.tenant_id == tid, TrustSnapshot.brand_id == bid, TrustSnapshot.domain == "grow").order_by(TrustSnapshot.ts.desc())
    res_snap = await session.execute(stmt_snap)
    snapshots = res_snap.scalars().all()
    assert len(snapshots) == 1
    latest_snap = snapshots[0]
    assert pytest.approx(latest_snap.score, abs=0.1) == 59.0
    assert latest_snap.tier == 0
