import pytest
import datetime as dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import (
    Tenant,
    Brand,
    Campaign,
    SpendFact,
    Touchpoint,
    Order,
    OrderLine,
    Refund,
    FulfillmentCost,
    TrustSnapshot
)
from app.profit.poas import calculate_campaign_poas


@pytest.mark.asyncio
async def test_standard_campaign_poas_calculation(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant, Brand
    async with async_session() as s:
        tenant = Tenant(name="POAS Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="POAS Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Setup 2 Campaigns
        c1 = Campaign(id="camp_google", tenant_id=tid, brand_id=bid, name="Google Sales", platform="google-ads", status="active")
        c2 = Campaign(id="camp_meta", tenant_id=tid, brand_id=bid, name="Meta Sales", platform="meta-ads", status="active")
        s.add_all([c1, c2])

        # Setup Spend Facts
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_google", amount_minor=10000, date=dt.date(2026, 6, 10))) # ₹100 spend
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_meta", amount_minor=20000, date=dt.date(2026, 6, 10))) # ₹200 spend

        # Setup Touchpoints
        tp1 = Touchpoint(tenant_id=tid, customer_id="cust_g", campaign_id="camp_google", type="click", occurred_at=dt.datetime(2026, 6, 10, 12, 0, 0))
        tp2 = Touchpoint(tenant_id=tid, customer_id="cust_m", campaign_id="camp_meta", type="click", occurred_at=dt.datetime(2026, 6, 10, 12, 30, 0))
        s.add_all([tp1, tp2])

        # Setup Orders
        # Order 1 (Google) - Rev: 13,000 minor, COGS: 5,000 minor, Fulfillment: 1,500 minor. Contrib: 6,500 minor
        o1 = Order(id="ord_1", tenant_id=tid, brand_id=bid, amount_minor=13000, currency="INR", customer_id="cust_g", placed_at=dt.datetime(2026, 6, 10, 14, 0, 0))
        s.add(o1)
        await s.commit()

        ol1 = OrderLine(id="ol_1", tenant_id=tid, order_id="ord_1", unit_price_minor=15000, line_discount_minor=2000, qty=1, unit_cost_minor=5000)
        fc1 = FulfillmentCost(tenant_id=tid, order_id="ord_1", shipping_cost_minor=1000, marketplace_fee_minor=500)
        s.add_all([ol1, fc1])

        # Order 2 (Meta) - Rev: 28,000 minor, COGS: 8,000 minor, Fulfillment: 2,000 minor. Contrib: 18,000 minor
        o2 = Order(id="ord_2", tenant_id=tid, brand_id=bid, amount_minor=28000, currency="INR", customer_id="cust_m", placed_at=dt.datetime(2026, 6, 10, 15, 0, 0))
        s.add(o2)
        await s.commit()

        ol2 = OrderLine(id="ol_2", tenant_id=tid, order_id="ord_2", unit_price_minor=30000, line_discount_minor=2000, qty=1, unit_cost_minor=8000)
        fc2 = FulfillmentCost(tenant_id=tid, order_id="ord_2", shipping_cost_minor=1500, marketplace_fee_minor=500)
        s.add_all([ol2, fc2])
        await s.commit()

    # 2. Run POAS calculation
    async with async_session() as s:
        reports = await calculate_campaign_poas(s, tid, bid)
        
        # There should be 2 campaign reports (Google spend > 0, Meta spend > 0)
        # Google: spend = 10,000 minor, contrib = 6,500 minor -> POAS = 0.65, ROAS = 1.3
        # Meta: spend = 20,000 minor, contrib = 18,000 minor -> POAS = 0.90, ROAS = 1.4
        # Sorted worst-POAS-first (Google poas = 0.65 is worst than Meta poas = 0.90)
        # So c1 (Google) is index 0, c2 (Meta) is index 1
        assert len(reports) == 2

        google_rep = reports[0]
        assert google_rep["campaign_id"] == "camp_google"
        assert google_rep["spend_minor"] == 10000
        assert google_rep["contribution_margin_minor"] == 6500
        assert google_rep["poas"] == 0.65
        assert google_rep["roas"] == 1.3
        assert google_rep["breakdown"]["gross_revenue_minor"] == 13000
        assert google_rep["breakdown"]["cogs_minor"] == 5000
        assert google_rep["breakdown"]["estimated_cogs"] is False

        meta_rep = reports[1]
        assert meta_rep["campaign_id"] == "camp_meta"
        assert meta_rep["spend_minor"] == 20000
        assert meta_rep["contribution_margin_minor"] == 18000
        assert meta_rep["poas"] == 0.90
        assert meta_rep["roas"] == 1.4
        assert meta_rep["breakdown"]["gross_revenue_minor"] == 28000
        assert meta_rep["breakdown"]["cogs_minor"] == 8000


@pytest.mark.asyncio
async def test_estimated_cogs_flag(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="POAS Tenant 2", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="POAS Brand 2")
        s.add(brand)
        await s.commit()
        bid = brand.id

        s.add(Campaign(id="camp_g2", tenant_id=tid, brand_id=bid, name="Google", platform="google-ads"))
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_g2", amount_minor=5000, date=dt.date(2026, 6, 10)))
        s.add(Touchpoint(tenant_id=tid, customer_id="cust_2", campaign_id="camp_g2", type="click", occurred_at=dt.datetime(2026, 6, 10, 12, 0, 0)))

        o = Order(id="ord_est", tenant_id=tid, brand_id=bid, amount_minor=10000, customer_id="cust_2", placed_at=dt.datetime(2026, 6, 10, 14, 0, 0))
        s.add(o)
        await s.commit()

        # Missing unit cost (unit_cost_minor=None) to trigger estimated cogs
        ol = OrderLine(id="ol_est", tenant_id=tid, order_id="ord_est", unit_price_minor=10000, line_discount_minor=0, qty=1, unit_cost_minor=None)
        s.add(ol)
        await s.commit()

    async with async_session() as s:
        reports = await calculate_campaign_poas(s, tid, bid)
        assert len(reports) == 1
        rep = reports[0]
        assert rep["campaign_id"] == "camp_g2"
        assert rep["breakdown"]["estimated_cogs"] is True
        assert rep["breakdown"]["cogs_minor"] == 0  # Missing cost defaults to 0


@pytest.mark.asyncio
async def test_all_lines_refunded_edge_case(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="POAS Tenant 3", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="POAS Brand 3")
        s.add(brand)
        await s.commit()
        bid = brand.id

        s.add(Campaign(id="camp_g3", tenant_id=tid, brand_id=bid, name="Google", platform="google-ads"))
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_g3", amount_minor=10000, date=dt.date(2026, 6, 10)))
        s.add(Touchpoint(tenant_id=tid, customer_id="cust_3", campaign_id="camp_g3", type="click", occurred_at=dt.datetime(2026, 6, 10, 12, 0, 0)))

        o = Order(id="ord_ref", tenant_id=tid, brand_id=bid, amount_minor=10000, customer_id="cust_3", placed_at=dt.datetime(2026, 6, 10, 14, 0, 0))
        s.add(o)
        await s.commit()

        ol = OrderLine(id="ol_ref", tenant_id=tid, order_id="ord_ref", unit_price_minor=10000, line_discount_minor=0, qty=1, unit_cost_minor=3000)
        fc = FulfillmentCost(tenant_id=tid, order_id="ord_ref", shipping_cost_minor=1000, marketplace_fee_minor=500)
        s.add_all([ol, fc])
        await s.commit()

        # Add refund matching full price (₹100)
        r = Refund(tenant_id=tid, order_line_id="ol_ref", amount_minor=10000)
        s.add(r)
        await s.commit()

    async with async_session() as s:
        reports = await calculate_campaign_poas(s, tid, bid)
        assert len(reports) == 1
        rep = reports[0]
        # Gross margin: 10000 - 3000 = 7000
        # Refunds: 10000
        # Fulfillment: 1500
        # Contribution margin: 7000 - 10000 - 1500 = -4500
        assert rep["contribution_margin_minor"] == -4500
        # POAS = -4500 / 10000 = -0.45
        assert rep["poas"] == -0.45


@pytest.mark.asyncio
async def test_custom_attribution_window(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="POAS Tenant 4", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="POAS Brand 4")
        s.add(brand)
        await s.commit()
        bid = brand.id

        s.add(Campaign(id="camp_g4", tenant_id=tid, brand_id=bid, name="Google", platform="google-ads"))
        s.add(SpendFact(tenant_id=tid, campaign_id="camp_g4", amount_minor=10000, date=dt.date(2026, 6, 10)))
        
        # Touchpoint is 40 days prior to order
        tp = Touchpoint(tenant_id=tid, customer_id="cust_4", campaign_id="camp_g4", type="click", occurred_at=dt.datetime(2026, 5, 1, 12, 0, 0))
        s.add(tp)

        o = Order(id="ord_att", tenant_id=tid, brand_id=bid, amount_minor=10000, customer_id="cust_4", placed_at=dt.datetime(2026, 6, 10, 14, 0, 0))
        s.add(o)
        await s.commit()

        ol = OrderLine(id="ol_att", tenant_id=tid, order_id="ord_att", unit_price_minor=10000, line_discount_minor=0, qty=1, unit_cost_minor=4000)
        s.add(ol)
        await s.commit()

    async with async_session() as s:
        # Default attribution window is 30 days -> touchpoint (40 days ago) is skipped -> attributes to ORGANIC
        reports_30 = await calculate_campaign_poas(s, tid, bid, attribution_window_days=30)
        # Organic report should have the contribution margin since campaign camp_g4 has 0 margin.
        organic_rep = [r for r in reports_30 if r["campaign_id"] == "ORGANIC"]
        assert len(organic_rep) == 1
        assert organic_rep[0]["contribution_margin_minor"] == 6000 # 10000 - 4000 = 6000

        # Custom attribution window is 45 days -> touchpoint (40 days ago) is valid -> attributes to camp_g4
        reports_45 = await calculate_campaign_poas(s, tid, bid, attribution_window_days=45)
        google_rep = [r for r in reports_45 if r["campaign_id"] == "camp_g4"]
        assert len(google_rep) == 1
        assert google_rep[0]["contribution_margin_minor"] == 6000
