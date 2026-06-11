import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant, Brand, BrandProperty, OpRow
from app.kernel import loop

@pytest.mark.asyncio
async def test_search_console_audit_flow(client, db_engine):
    async_session = sessionmaker = db_engine # wait, conftest supplies db_engine and client
    # Actually, we can use the async_sessionmaker directly
    from sqlalchemy.orm import sessionmaker as sa_sessionmaker
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
