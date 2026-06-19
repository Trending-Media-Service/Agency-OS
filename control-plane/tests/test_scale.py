import pytest
import datetime as dt
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Tenant, Brand, Order, OpRow, CostEntry
from app.kernel.optypes import OpState
from app.tasks.graduation import check_and_propose_graduations, GRADUATION_THRESHOLD_MINOR

@pytest.mark.asyncio
async def test_scale_onboarding_and_graduation_e2e(client: AsyncClient, session):
    # 1. Onboard a new brand on the shared tier (default)
    # Call POST /tenants
    r = await client.post("/tenants", json={"name": "Aos Wellness", "brand_name": "Wellness Foods"})
    assert r.status_code == 200
    res_data = r.json()
    tid = res_data["tenant_id"]
    bid = res_data["brand_id"]
    H = {"X-Tenant-ID": tid}

    # Verify that the Tenant hosting tier is "shared" in DB
    # We must use a direct session query, setting the RLS tenant context
    if session.bind and session.bind.dialect.name == "postgresql":
        from sqlalchemy import text
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tid}
        )
    
    tenant = await session.get(Tenant, tid)
    assert tenant is not None
    assert tenant.hosting_tier == "shared"

    # 2. Check graduation task when total sales are below threshold
    # Add a small order: 50,000 INR = 500,000 minor units
    small_order = Order(
        id="ord_small",
        tenant_id=tid,
        brand_id=bid,
        amount_minor=500_000,
        currency="INR",
        placed_at=dt.datetime.now(dt.timezone.utc)
    )
    session.add(small_order)
    await session.commit()

    # Run check_and_propose_graduations
    # It queries across all tenants, so we run it on the session directly (simulating scheduler)
    await check_and_propose_graduations(session)
    await session.commit()

    # Verify that NO graduation Op was proposed
    stmt = select(OpRow).where(
        OpRow.tenant_id == tid,
        OpRow.action == "provision.brand_baseline.update"
    )
    res = await session.execute(stmt)
    assert res.scalar_one_or_none() is None

    # 3. Check graduation task when total sales exceed the threshold
    # Add a large order to push it above 500,000 INR (5,000,000 minor units)
    # Total will be 500,000 + 4,800,000 = 5,300,000 minor units
    large_order = Order(
        id="ord_large",
        tenant_id=tid,
        brand_id=bid,
        amount_minor=4_800_000,
        currency="INR",
        placed_at=dt.datetime.now(dt.timezone.utc)
    )
    session.add(large_order)
    await session.commit()

    # Run check_and_propose_graduations again
    await check_and_propose_graduations(session)
    await session.commit()

    # Verify that a graduation Op HAS been proposed!
    res = await session.execute(stmt)
    grad_op = res.scalar_one_or_none()
    assert grad_op is not None
    assert grad_op.state == "AWAITING_APPROVAL"
    assert grad_op.params["tier"] == "dedicated"

    # 4. Attempt to run graduation task again and verify it does NOT propose duplicate Ops
    await check_and_propose_graduations(session)
    await session.commit()
    
    # Verify count is still exactly 1
    count_stmt = select(OpRow).where(
        OpRow.tenant_id == tid,
        OpRow.action == "provision.brand_baseline.update"
    )
    res_count = await session.execute(count_stmt)
    assert len(res_count.scalars().all()) == 1

    # 5. Approve and execute the graduation Op E2E!
    # Call POST /ops/{op_id}/decision
    decision_res = await client.post(
        f"/ops/{grad_op.id}/decision",
        headers=H,
        json={
            "decision": "approve",
            "actor": "owner_dave",
            "role": "AGENCY_OWNER",
            "surface": "web",
            "reason": "Graduating successful brand to dedicated project"
        }
    )
    assert decision_res.status_code == 200

    # Verify that the Op is now APPROVED and has queued an outbox item
    # Wait, in the test client, background tasks run synchronously or we can drain the outbox programmatically.
    # Let's drain the outbox programmatically using POST /tasks/drain-outbox
    drain_res = await client.post("/tasks/drain-outbox")
    assert drain_res.status_code == 200

    # Refresh OpRow and Tenant from database using populate_existing to bypass session cache asynchronously
    await session.commit()
    
    op_stmt = select(OpRow).where(OpRow.id == grad_op.id).execution_options(populate_existing=True)
    op_res = await session.execute(op_stmt)
    grad_op_fresh = op_res.scalar_one()
    assert grad_op_fresh.state == OpState.DONE

    # 6. Verify that the Tenant's hosting tier has graduated to "dedicated" in DB!
    tenant_stmt = select(Tenant).where(Tenant.id == tid).execution_options(populate_existing=True)
    tenant_res = await session.execute(tenant_stmt)
    tenant_fresh = tenant_res.scalar_one()
    assert tenant_fresh.hosting_tier == "dedicated"

    # 7. Verify that cost ledger entries were emitted for the newly provisioned resources
    cost_stmt = select(CostEntry).where(CostEntry.tenant_id == tid, CostEntry.op_id == grad_op.id)
    cost_res = await session.execute(cost_stmt)
    costs = cost_res.scalars().all()
    assert len(costs) > 0
    assert any(c.kind == "api_call" for c in costs)
    
    # 8. Fetch portfolio overview API and verify response structure
    portfolio_res = await client.get("/brands/portfolio", headers=H)
    assert portfolio_res.status_code == 200
    pf_data = portfolio_res.json()
    assert pf_data["tenant_id"] == tid
    assert pf_data["hosting_tier"] == "dedicated"
    assert len(pf_data["portfolio"]) == 1
    assert pf_data["portfolio"][0]["brand_id"] == bid
    assert pf_data["portfolio"][0]["total_cost_minor"] > 0
    
    # 9. Fetch cost rollup API and verify response
    cost_rollup_res = await client.get("/costs/rollup", headers=H)
    assert cost_rollup_res.status_code == 200
    rollup_data = cost_rollup_res.json()
    assert rollup_data["tenant_id"] == tid
    assert "api_call" in rollup_data["rollup"]
