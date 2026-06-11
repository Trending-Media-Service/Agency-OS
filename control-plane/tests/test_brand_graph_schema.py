import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tenant, Brand, BrandProperty

@pytest.mark.asyncio
async def test_brand_property_crud(session: AsyncSession):
    # 1. Create a Tenant and Brand
    tenant = Tenant(name="Test Tenant", hosting_tier="shared")
    session.add(tenant)
    await session.commit()
    
    brand = Brand(tenant_id=tenant.id, name="Tanmatra")
    session.add(brand)
    await session.commit()
    
    # 2. Add Brand Properties (domain and analytics)
    prop1 = BrandProperty(
        tenant_id=tenant.id,
        brand_id=brand.id,
        type="domain",
        provider="godaddy",
        connection_ref="secret/godaddy-creds"
    )
    prop2 = BrandProperty(
        tenant_id=tenant.id,
        brand_id=brand.id,
        type="analytics",
        provider="ga4",
        status="sensing",
        findings={"ga4_tag_present": True}
    )
    session.add_all([prop1, prop2])
    await session.commit()
    
    # Refresh to verify DB retrieval
    await session.refresh(brand)
    assert len(brand.properties) == 2
    
    # Verify values and default values
    d_prop = next(p for p in brand.properties if p.type == "domain")
    assert d_prop.provider == "godaddy"
    assert d_prop.connection_ref == "secret/godaddy-creds"
    assert d_prop.status == "absent" # default value
    assert d_prop.findings == {} # default value
    
    a_prop = next(p for p in brand.properties if p.type == "analytics")
    assert a_prop.provider == "ga4"
    assert a_prop.status == "sensing"
    assert a_prop.findings == {"ga4_tag_present": True}
    
    # 3. Update property values
    d_prop.status = "connected"
    d_prop.findings = {"nameservers": ["ns1.godaddy.com"]}
    await session.commit()
    
    # Query database directly
    res = await session.execute(
        select(BrandProperty).where(BrandProperty.brand_id == brand.id, BrandProperty.type == "domain")
    )
    updated_prop = res.scalar_one()
    assert updated_prop.status == "connected"
    assert updated_prop.findings == {"nameservers": ["ns1.godaddy.com"]}

@pytest.mark.asyncio
async def test_brand_relationship_cascade(session: AsyncSession):
    # 1. Create Tenant, Brand, and Property
    tenant = Tenant(name="Cascade Tenant")
    session.add(tenant)
    await session.commit()
    
    brand = Brand(tenant_id=tenant.id, name="Cascade Brand")
    session.add(brand)
    await session.commit()
    
    prop = BrandProperty(
        tenant_id=tenant.id,
        brand_id=brand.id,
        type="whatsapp",
        provider="meta",
        status="healthy"
    )
    session.add(prop)
    await session.commit()
    
    prop_id = prop.id
    
    # Verify it exists
    res = await session.execute(select(BrandProperty).where(BrandProperty.id == prop_id))
    assert res.scalar_one_or_none() is not None
    
    # 2. Delete the Brand and verify Cascade deletes properties
    await session.delete(brand)
    await session.commit()
    
    # Check that property is deleted
    res_after = await session.execute(select(BrandProperty).where(BrandProperty.id == prop_id))
    assert res_after.scalar_one_or_none() is None
