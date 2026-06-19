import pytest
import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Tenant, Brand, BrandObjective, BrandProperty, Connection, OpRow, TrustSnapshot, Campaign, Order
from app.services.recommender import get_recommendations
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.kernel import loop

@pytest.mark.asyncio
async def test_recommender_footprint_baseline(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Rec Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id
        
        brand = Brand(tenant_id=tenant_id, name="Footprint Brand")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        # Seed footprint objective
        obj = BrandObjective(tenant_id=tenant_id, brand_id=brand_id, objective="footprint")
        s.add(obj)
        await s.commit()

    # 2. Get recommendations (No connections exists yet)
    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        
        # Should recommend:
        # - Connect Google (presence.google.connect)
        # - Run Playwright citation audit (presence.citation.audit)
        actions = {r.action for r in recs}
        assert "presence.google.connect" in actions
        assert "presence.citation.audit" in actions
        assert len(recs) == 2

    # 3. Add Google connection and rerun
    async with async_session() as s:
        conn = Connection(tenant_id=tenant_id, brand_id=brand_id, provider="google", credential="ref", scope="read")
        s.add(conn)
        await s.commit()

    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        
        # Now Google is connected, should recommend GSC and GMC audits!
        actions = {r.action for r in recs}
        assert "presence.search_console.audit" in actions
        assert "presence.merchant_center.audit" in actions
        assert "presence.citation.audit" in actions # still here since citation property is absent
        assert "presence.google.connect" not in actions
        assert len(recs) == 3

    # 4. Propose one recommendation and verify it is filtered out (duplicate prevention)
    async with async_session() as s:
        # Propose the search console audit
        gsc_op = OpSpec(
            tenant_id=tenant_id,
            brand_id=brand_id,
            domain="presence",
            action="presence.search_console.audit",
            params={"brand_id": brand_id},
            severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
        )
        await loop.propose(s, gsc_op, actor="operator")
        await s.commit()

    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        actions = {r.action for r in recs}
        
        # presence.search_console.audit should now be filtered out!
        assert "presence.search_console.audit" not in actions
        assert "presence.merchant_center.audit" in actions
        assert "presence.citation.audit" in actions
        assert len(recs) == 2


@pytest.mark.asyncio
async def test_recommender_growth_reallocation(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Bootstrap Tenant, Brand, and growth objective
    async with async_session() as s:
        tenant = Tenant(name="Rec Growth Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id
        
        brand = Brand(tenant_id=tenant_id, name="Growth Brand")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        obj = BrandObjective(tenant_id=tenant_id, brand_id=brand_id, objective="growth")
        s.add(obj)
        await s.commit()

    # 2. Rerun: growth with no connections should recommend connecting Google
    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        actions = {r.action for r in recs}
        assert "presence.google.connect" in actions

    # 3. Connect Google, seed active campaigns, and add orders with ROAS imbalance
    async with async_session() as s:
        conn = Connection(tenant_id=tenant_id, brand_id=brand_id, provider="google", credential="ref", scope="read")
        s.add(conn)
        
        camp_g = Campaign(id="camp-g1", tenant_id=tenant_id, brand_id=brand_id, name="Google Search Ads", platform="google-ads", status="active")
        camp_m = Campaign(id="camp-m1", tenant_id=tenant_id, brand_id=brand_id, name="Meta Social Ads", platform="meta-ads", status="active")
        s.add_all([camp_g, camp_m])
        await s.commit()

        # Seed orders to Meta to simulate high ROI (2.0)
        order = Order(id="order-1", tenant_id=tenant_id, brand_id=brand_id, amount_minor=500000, currency="INR", attributed_campaign_id="camp-m1", placed_at=dt.datetime.utcnow())
        s.add(order)
        await s.commit()

    # 4. Scenario A: High Trust Score (>= 80) -> Reallocation RECOMMENDED
    async with async_session() as s:
        # Seed healthy trust snapshot
        snap = TrustSnapshot(tenant_id=tenant_id, brand_id=brand_id, domain="grow", score=90.0, tier=2)
        s.add(snap)
        await s.commit()

    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        actions = {r.action for r in recs}
        assert "grow.budget.reallocate" in actions

    # 5. Scenario B: Low Trust Score (< 80) -> Reallocation BLOCKED (Safety rule)
    async with async_session() as s:
        # Overwrite with bad trust snapshot
        snap_bad = TrustSnapshot(tenant_id=tenant_id, brand_id=brand_id, domain="grow", score=55.0, tier=1, ts=dt.datetime.utcnow() + dt.timedelta(seconds=1))
        s.add(snap_bad)
        await s.commit()

    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        actions = {r.action for r in recs}
        
        # Should NOT recommend budget reallocate because trust score is low!
        assert "grow.budget.reallocate" not in actions


@pytest.mark.asyncio
async def test_recommender_retention_wordpress(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Bootstrap Brand with retention objective
    async with async_session() as s:
        tenant = Tenant(name="Rec Ret Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id
        
        brand = Brand(tenant_id=tenant_id, name="Retention Brand")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        obj = BrandObjective(tenant_id=tenant_id, brand_id=brand_id, objective="retention")
        s.add(obj)
        await s.commit()

    # 2. Get recommendations -> should recommend wordpress connection
    async with async_session() as s:
        recs = await get_recommendations(s, brand_id)
        actions = {r.action for r in recs}
        assert "presence.wordpress.connect" in actions


@pytest.mark.asyncio
async def test_recommender_bscore_non_gating_invariant(client, db_engine):
    """Verify that recommendations (advisory B-score/recommender engine) never alter policy gate decisions."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Rec Gating Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id
        
        brand = Brand(tenant_id=tenant_id, name="Gating Brand")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    # 2. Propose a normal provision operation that should pass policy checks
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="provision",
        action="provision.web_host.create",
        params={"domain": "woktok.in", "recipe": "web-host", "version": "0.1.0"},
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=10000, currency="INR")
    )
    
    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="operator")
        await s.commit()
        
        # Evaluate policy gate (should pass)
        gate, req = await loop.preview_and_gate(s, row, tier=2)
        assert len(gate.violations) == 0
        assert row.state == "APPROVED"


@pytest.mark.asyncio
async def test_recommender_api_endpoints(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    
    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="API Rec Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id
        
        brand = Brand(tenant_id=tenant_id, name="API Rec Brand")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # 2. GET active objective (should default to footprint)
    resp = await client.get(f"/brands/{brand_id}/objective", headers=H)
    assert resp.status_code == 200
    assert resp.json()["objective"] == "footprint"

    # 3. POST bad objective value -> should return 400
    resp_bad = await client.post(f"/brands/{brand_id}/objective", headers=H, json={"objective": "invalid_obj"})
    assert resp_bad.status_code == 400

    # 4. POST valid objective value -> should return 200 and update DB
    resp_good = await client.post(f"/brands/{brand_id}/objective", headers=H, json={"objective": "growth"})
    assert resp_good.status_code == 200
    assert resp_good.json()["objective"] == "growth"

    # Verify database was updated
    async with async_session() as s:
        stmt = select(BrandObjective).where(BrandObjective.brand_id == brand_id)
        res = await s.execute(stmt)
        obj_db = res.scalar_one()
        assert obj_db.objective == "growth"

    # 5. GET recommendations from API (since no connections, should recommend Google connect!)
    resp_recs = await client.get(f"/brands/{brand_id}/recommendations", headers=H)
    assert resp_recs.status_code == 200
    recs = resp_recs.json()
    assert len(recs) == 1
    assert recs[0]["action"] == "presence.google.connect"
    assert "Connect Google Search Console" in recs[0]["preview_summary"]
    assert recs[0]["domain"] == "presence"
    assert recs[0]["impact"] == 1
    assert recs[0]["reversibility"] == "COMPENSATABLE"
    assert recs[0]["cost_minor"] == 0

