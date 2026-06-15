import pytest
from sqlalchemy import select
from app.models import OpRow, TrustSnapshot, Approval
from app.services.marketing import MockMarketingClient

@pytest.fixture(autouse=True)
def clear_marketing_client():
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()

@pytest.mark.asyncio
async def test_grow_campaign_modify_flow(client, session):
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

    # 2. Propose campaign create via intent
    resp_intent = await client.post("/intents", headers=H, json={
        "domain": "grow",
        "brand_id": bid,
        "text": "create ad campaign SummerSale budget 10000 bid 150"
    })
    assert resp_intent.status_code == 200
    intent_data = resp_intent.json()
    assert len(intent_data["cards"]) == 1
    op_card = intent_data["cards"][0]
    assert op_card["state"] == "AWAITING_APPROVAL"
    op_id = op_card["op_id"]

    # Verify initial params in DB
    async with session.begin_nested(): # Use nested transaction to inspect DB without committing
        row = await session.get(OpRow, op_id)
        assert row.params["budget_minor"] == 1000000
        assert row.params["bid_minor"] == 15000
        assert row.cost_amount_minor == 1000000
        session.expire(row)

    # 3. Call modify decision to tweak budget and bid
    resp_mod = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "modify",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp",
        "reason": "change budget to 4000 and bid to 40"
    })
    assert resp_mod.status_code == 200
    mod_data = resp_mod.json()
    # It should transition back to AWAITING_APPROVAL after previewing/gating the modified version
    assert mod_data["state"] == "AWAITING_APPROVAL"

    # Verify modified params in DB
    async with session.begin_nested():
        row = await session.get(OpRow, op_id)
        assert row.params["budget_minor"] == 400000
        assert row.params["bid_minor"] == 4000
        assert row.cost_amount_minor == 400000
        assert row.state == "AWAITING_APPROVAL"

    # 4. Approve the modified Op
    resp_app = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_app.status_code == 200
    assert resp_app.json()["state"] == "APPROVED"

    # 5. Run outbox drain to execute the approved campaign creation
    # In E2E tests, the background task runs asynchronously or we trigger it via FastAPI background tasks.
    # Since we are using client (which uses ASGITransport), background tasks are run during the request context?
    # Actually, ASGITransport runs background tasks before returning if we don't mock it, but wait.
    # In conftest client fixture:
    # yield ac
    # It doesn't explicitly run background tasks if they are not awaited, but FastAPI background tasks are executed after response is sent.
    # To be sure, we can trigger the drain endpoint manually (like we did in test_kernel.py E2E tests).
    resp_drain = await client.post("/tasks/drain-outbox")
    assert resp_drain.status_code == 200

    # 6. Verify campaign is executed in MockMarketingClient with modified params
    m_client = MockMarketingClient()
    campaign_id = f"camp-{bid}-summersale"
    camp = await m_client.get_campaign(campaign_id)
    assert camp is not None
    assert camp["budget_minor"] == 400000
    assert camp["bid_minor"] == 4000
    assert camp["status"] == "ACTIVE"
