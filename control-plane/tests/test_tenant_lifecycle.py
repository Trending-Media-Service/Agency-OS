import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, Brand, Connection, OpRow, AuditEvent
from app.middleware import VALID_TENANTS_CACHE

@pytest.mark.asyncio
async def test_tenant_lifecycle_suspension(client: AsyncClient, session: AsyncSession):
    """Verify that operators can suspend a tenant, and suspended tenants are immediately blocked by gateway."""
    # Enable tenant validation for this test
    import app.main as mainmod
    mainmod.app.state.bypass_tenant_validation = False
    VALID_TENANTS_CACHE.clear()

    try:
        # 1. Create a new Tenant (passing the correct default-dev-token)
        create_resp = await client.post(
            "/tenants",
            json={"name": "Suspension Inc", "brand_name": "Suspension Brand"},
            headers={"Authorization": "Bearer default-dev-token"}
        )
        assert create_resp.status_code == 200
        data = create_resp.json()
        tenant_id = data["tenant_id"]
        brand_id = data["brand_id"]
        
        # Verify it exists and is active by default in DB
        res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = res.scalar_one()
        assert tenant.is_active is True
        
        # 2. Call a standard tenant-scoped endpoint (should pass)
        resp = await client.get("/connections", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        
        # 3. Suspend the Tenant as Operator
        patch_resp = await client.patch(
            f"/tenants/{tenant_id}",
            json={"is_active": False},
            headers={"Authorization": "Bearer default-dev-token"}
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_active"] is False
        
        # Verify status in DB
        await session.refresh(tenant)
        assert tenant.is_active is False
        
        # 4. Try to call the tenant-scoped endpoint again (should fail with 403 Forbidden)
        resp_suspended = await client.get("/connections", headers={"X-Tenant-ID": tenant_id})
        assert resp_suspended.status_code == 403
        assert "suspended" in resp_suspended.json()["detail"].lower()
        
        # 5. Re-activate the Tenant
        patch_resp = await client.patch(
            f"/tenants/{tenant_id}",
            json={"is_active": True},
            headers={"Authorization": "Bearer default-dev-token"}
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_active"] is True
        
        # Verify status in DB
        await session.refresh(tenant)
        assert tenant.is_active is True
        
        # 6. Call the endpoint again (should pass again!)
        resp_active = await client.get("/connections", headers={"X-Tenant-ID": tenant_id})
        assert resp_active.status_code == 200
        
    finally:
        # Restore bypass flag to prevent breaking other tests
        mainmod.app.state.bypass_tenant_validation = True
        VALID_TENANTS_CACHE.clear()


@pytest.mark.asyncio
async def test_tenant_lifecycle_cascading_deletion(client: AsyncClient, session: AsyncSession):
    """Verify that deleting a tenant cleanly cascade deletes all associated brand, connections, and ops."""
    # 1. Create Tenant
    t = Tenant(id="t-lifecycle-del", name="Delete Inc", is_active=True)
    session.add(t)
    await session.flush()
    
    # 2. Add dependent child resources
    b = Brand(id="b-lifecycle-del", tenant_id=t.id, name="Delete Brand")
    c = Connection(id="c-lifecycle-del", tenant_id=t.id, brand_id=b.id, provider="google")
    
    # Specify all required NOT NULL columns for OpRow (impact, reversibility, idem_key)
    op = OpRow(
        id="op-lifecycle-del",
        tenant_id=t.id,
        brand_id=b.id,
        domain="grow",
        action="grow.bid",
        state="PENDING",
        impact=1,
        reversibility="reversible",
        idem_key="idem-lifecycle-del"
    )
    
    # Include a dummy prev_hash to satisfy NOT NULL constraints on AuditEvent ledger
    audit = AuditEvent(
        ts="2026-06-20T00:00:00Z",
        tenant_id=t.id,
        actor="operator",
        action="grow.bid",
        op_id=op.id,
        payload={},
        prev_hash="genesis-hash",
        hash="mock-hash"
    )
    
    session.add_all([b, c, op, audit])
    await session.commit()
    
    # Verify they exist in DB
    assert (await session.execute(select(Brand).where(Brand.id == b.id))).scalar_one_or_none() is not None
    assert (await session.execute(select(Connection).where(Connection.id == c.id))).scalar_one_or_none() is not None
    assert (await session.execute(select(OpRow).where(OpRow.id == op.id))).scalar_one_or_none() is not None
    assert (await session.execute(select(AuditEvent).where(AuditEvent.op_id == op.id))).scalar_one_or_none() is not None
    
    # 3. Delete the Tenant via Operator Endpoint (passing correct token)
    del_resp = await client.delete(
        f"/tenants/{t.id}",
        headers={"Authorization": "Bearer default-dev-token"}
    )
    assert del_resp.status_code == 204
    
    # 4. Verify cascading deletion: all child resources must be automatically deleted
    session.expunge_all()
    
    assert (await session.execute(select(Tenant).where(Tenant.id == t.id))).scalar_one_or_none() is None
    assert (await session.execute(select(Brand).where(Brand.id == b.id))).scalar_one_or_none() is None
    assert (await session.execute(select(Connection).where(Connection.id == c.id))).scalar_one_or_none() is None
    assert (await session.execute(select(OpRow).where(OpRow.id == op.id))).scalar_one_or_none() is None
    assert (await session.execute(select(AuditEvent).where(AuditEvent.op_id == op.id))).scalar_one_or_none() is None
