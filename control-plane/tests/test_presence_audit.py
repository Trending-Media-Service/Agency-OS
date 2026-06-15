import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant, Brand, BrandProperty, OpRow, ConsentBasis
from app.kernel import loop

@pytest.mark.asyncio
async def test_search_console_audit_flow(client, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Presence Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # 2. Submit Intent: "audit search console for Tanmatra"
    resp = await client.post("/intents", headers=H, json={
        "domain": "presence",
        "brand_id": brand_id,
        "text": "audit search console for Tanmatra"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["cards"]) == 1

    card = data["cards"][0]
    op_id = card["op_id"]
    assert "Search Console" in card["preview"]

    # 3. Approve the planned audit operation
    resp_dec = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_dec.status_code == 200

    # 5. Verify database states:
    # BrandProperty should be updated with GSC findings
    async with async_session() as s:
        # Retrieve OpRow to verify it completed
        stmt_op = select(OpRow).where(OpRow.id == op_id)
        res_op = await s.execute(stmt_op)
        op_row = res_op.scalar_one()
        assert op_row.state == "DONE"

        # Check BrandProperty state
        stmt_prop = select(BrandProperty).where(
            BrandProperty.brand_id == brand_id,
            BrandProperty.type == "search_console"
        )
        res_prop = await s.execute(stmt_prop)
        prop = res_prop.scalar_one()
        assert prop.status == "degraded"
        assert prop.provider == "google"
        assert prop.findings["crawl_errors"] == 4
        assert "Missing schema.org markup on blog pages" in prop.findings["warnings"]

@pytest.mark.asyncio
async def test_merchant_center_audit_flow(client, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Presence Tenant 2", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra GMC")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        cb = ConsentBasis(
            tenant_id=tenant_id,
            category="vendor_sharing",
            action_or_vendor="google",
            status="granted",
            granted_by="owner"
        )
        s.add(cb)
        await s.commit()

    H = {"X-Tenant-ID": tenant_id}

    # 2. Submit Intent: "run merchant center feed verification"
    resp = await client.post("/intents", headers=H, json={
        "domain": "presence",
        "brand_id": brand_id,
        "text": "run merchant center feed verification"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["cards"]) == 1

    card = data["cards"][0]
    op_id = card["op_id"]
    assert "Merchant Center" in card["preview"]

    # 3. Approve and Execute
    resp_dec = await client.post(f"/ops/{op_id}/decision", headers=H, json={
        "decision": "approve",
        "actor": "chandan",
        "role": "owner",
        "surface": "whatsapp"
    })
    assert resp_dec.status_code == 200

    # 4. Verify BrandProperty state
    async with async_session() as s:
        stmt_prop = select(BrandProperty).where(
            BrandProperty.brand_id == brand_id,
            BrandProperty.type == "merchant_feed"
        )
        res_prop = await s.execute(stmt_prop)
        prop = res_prop.scalar_one()
        assert prop.status == "healthy"
        assert prop.findings["disapproved_products"] == 0
        assert prop.findings["active_items"] == 128


@pytest.mark.asyncio
async def test_merchant_center_feed_health_warnings_and_alert_dispatch(client, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.kernel.services import compute_snapshots
    from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
    from app.models import TrustSnapshot

    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="GMC Alert Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra GMC Alert")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        cb = ConsentBasis(
            tenant_id=tenant_id,
            category="vendor_sharing",
            action_or_vendor="google",
            status="granted",
            granted_by="owner"
        )
        s.add(cb)
        await s.commit()

    H = {"X-Tenant-ID": tenant_id}

    # 2. Directly propose GMC audit with 6 simulated disapproved items
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="presence",
        action="presence.merchant_center.audit",
        params={"brand_id": brand_id, "simulate_disapproved_products": 6},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="test")
        await loop.preview_and_gate(s, row, tier=2)
        await s.commit()

    # 3. Execute
    async with async_session() as s:
        # Directly execute the op via drain
        processed = await loop.drain_once(s)
        assert processed == 1
        await s.commit()

    # 4. Verify BrandProperty was set with findings, and ALERT_DISPATCH Op was spawned
    async with async_session() as s:
        stmt_prop = select(BrandProperty).where(
            BrandProperty.brand_id == brand_id,
            BrandProperty.type == "merchant_feed"
        )
        res_prop = await s.execute(stmt_prop)
        prop = res_prop.scalar_one()

        # Print debug traces
        from app.models import OpTrace
        res_t = await s.execute(select(OpTrace).where(OpTrace.op_id == row.id))
        for t in res_t.scalars().all():
            print(f"DEBUG_TRACE: {t.kind} -> {t.detail}")

        assert prop.status == "degraded"
        assert prop.findings["disapproved_products"] == 6

        # Assert ALERT_DISPATCH was created and is APPROVED
        stmt_alert = select(OpRow).where(
            OpRow.tenant_id == tenant_id,
            OpRow.brand_id == brand_id,
            OpRow.action == "presence.alert_dispatch"
        )
        res_alert = await s.execute(stmt_alert)
        alert_row = res_alert.scalar_one()
        assert alert_row.state == "APPROVED"
        assert alert_row.params["disapproved_products"] == 6

    # 4b. Execute the alert_dispatch op
    async with async_session() as s:
        processed_alert = await loop.drain_once(s)
        assert processed_alert == 1
        await s.commit()

    async with async_session() as s:
        res_alert = await s.execute(stmt_alert)
        alert_row = res_alert.scalar_one()
        assert alert_row.state == "DONE"

    # 5. Compute snapshots and assert gmc_critical_mismatches deducted from trust score
    async with async_session() as s:
        await compute_snapshots(s)
        await s.commit()

    async with async_session() as s:
        stmt_snap = select(TrustSnapshot).where(
            TrustSnapshot.tenant_id == tenant_id,
            TrustSnapshot.brand_id == brand_id,
            TrustSnapshot.domain == "manage" # feed health impacts manage trust domain
        ).order_by(TrustSnapshot.ts.desc()).limit(1)
        res_snap = await s.execute(stmt_snap)
        snap = res_snap.scalar_one()
        # Bounded score should be ~ 67.0 - saturating_penalty(6, 25.0, 5.0) => 67.0 - 17.47 = 49.53
        assert 49.0 <= snap.score <= 50.0

