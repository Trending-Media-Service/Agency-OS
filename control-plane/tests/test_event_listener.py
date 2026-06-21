import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant, Brand

@pytest.mark.asyncio
async def test_dynamic_auto_seed_listener(session: AsyncSession):
    """Test that our before_flush listener dynamically seeds a missing tenant on-the-fly."""
    print("\n--- START TEST ---")
    
    # Create a brand with a completely new, unseeded tenant ID
    dynamic_tid = "t-dynamic-test-999"
    b = Brand(id="b-dynamic-test-999", tenant_id=dynamic_tid, name="Dynamic Brand")
    
    print("Adding brand to session...")
    session.add(b)
    
    print("Committing session (should trigger before_flush and auto-seed)...")
    await session.commit()
    print("Commit complete!")
    
    # Verify that the tenant was automatically created in the DB!
    res_t = await session.execute(select(Tenant).where(Tenant.id == dynamic_tid))
    tenant = res_t.scalar_one_or_none()
    assert tenant is not None
    assert tenant.name == f"Auto Seeded {dynamic_tid}"
    
    # Verify that the brand was also created successfully
    res_b = await session.execute(select(Brand).where(Brand.id == b.id))
    brand = res_b.scalar_one_or_none()
    assert brand is not None
    assert brand.tenant_id == dynamic_tid
    
    print("--- END TEST ---")
