import pytest
import datetime as dt
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Tenant, Brand, BrandProperty, Campaign, SpendFact, Touchpoint, Order, OrderLine
from app.profit.brand_score import calculate_brand_score


@pytest.mark.asyncio
async def test_brand_score_calculation_default_weights(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="Score Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Score Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # UX component (type: ux_analytics)
        # 5% conversion rate (0.05) -> min(100.0, 0.05 * 2000.0) = 100.0
        # 1.5% conversion rate (0.015) -> min(100.0, 0.015 * 2000.0) = 30.0
        prop_ux = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="ux_analytics",
            provider="shopify",
            findings={"conversion_rate": 0.015}
        )

        # Organic component (type: presence_audit)
        # 80% coverage -> ratio = 0.8 -> score = 80.0
        prop_org = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="presence_audit",
            provider="google",
            findings={"indexing_coverage_ratio": 0.8}
        )

        # PR component (type: pr_monitoring)
        # Normalized volume: 45.0 -> score = 45.0
        prop_pr = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="pr_monitoring",
            provider="google",
            findings={"mention_volume_normalized": 45.0}
        )

        s.add_all([prop_ux, prop_org, prop_pr])
        await s.commit()

        # Setup Paid Campaign to verify Paid Component
        c = Campaign(id="camp_score", tenant_id=tid, brand_id=bid, name="Google Score Ads", platform="google-ads", status="active")
        s.add(c)
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_score", amount_minor=10000, date=dt.date(2026, 6, 10))) # ₹100 spend
        s.add(Touchpoint(tenant_id=tid, customer_id="cust_s", campaign_id="camp_score", type="click", occurred_at=dt.datetime(2026, 6, 10, 12, 0, 0)))
        
        # Order - Rev: 20000, COGS: 8000 -> Contribution: 12000 minor
        # POAS = 12000 / 10000 = 1.2
        # Paid val = min(100.0, 1.2 * 50.0) = 60.0
        o = Order(id="ord_s", tenant_id=tid, brand_id=bid, amount_minor=20000, customer_id="cust_s", placed_at=dt.datetime(2026, 6, 10, 14, 0, 0))
        s.add(o)
        await s.commit()

        ol = OrderLine(id="ol_s", tenant_id=tid, order_id="ord_s", unit_price_minor=20000, qty=1, unit_cost_minor=8000)
        s.add(ol)
        await s.commit()

    async with async_session() as s:
        # Calculate Brand Score:
        # UX: 30.0 * 0.3 = 9.0
        # Org: 80.0 * 0.2 = 16.0
        # Paid: 60.0 * 0.4 = 24.0
        # PR: 45.0 * 0.1 = 4.5
        # Expected score: 9.0 + 16.0 + 24.0 + 4.5 = 53.5
        score = await calculate_brand_score(s, tid, bid)
        assert score == 53.5


@pytest.mark.asyncio
async def test_brand_score_calculation_custom_weights(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="Score Tenant Custom", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Score Brand Custom")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Custom Weights: UX=0.1, Org=0.5, Paid=0.2, PR=0.2
        # Sum = 1.0
        prop_weights = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="brand_performance_weights",
            provider="system",
            findings={"w_ux": 0.1, "w_organic": 0.5, "w_paid": 0.2, "w_pr": 0.2}
        )

        # UX: 3% -> conversion_rate = 0.03 -> score = min(100.0, 0.03 * 2000.0) = 60.0
        prop_ux = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="ux_analytics",
            provider="shopify",
            findings={"conversion_rate": 0.03}
        )

        # Org: 90% coverage -> score = 90.0
        prop_org = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="presence_audit",
            provider="google",
            findings={"indexing_coverage_ratio": 0.9}
        )

        # PR: 70.0 -> score = 70.0
        prop_pr = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="pr_monitoring",
            provider="google",
            findings={"mention_volume_normalized": 70.0}
        )

        s.add_all([prop_weights, prop_ux, prop_org, prop_pr])
        await s.commit()

        # No paid campaigns -> calculate_brand_score falls back to paid_val = 50.0

    async with async_session() as s:
        # Calculate Brand Score:
        # UX: 60.0 * 0.1 = 6.0
        # Org: 90.0 * 0.5 = 45.0
        # Paid: 50.0 * 0.2 = 10.0
        # PR: 70.0 * 0.2 = 14.0
        # Expected: 6.0 + 45.0 + 10.0 + 14.0 = 75.0
        score = await calculate_brand_score(s, tid, bid)
        assert score == 75.0
