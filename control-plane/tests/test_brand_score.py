import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models import (
    Tenant,
    Brand,
    BrandProperty,
    Campaign,
    SpendFact,
    Touchpoint,
    Order,
    OrderLine,
    FulfillmentCost
)
import datetime as dt

@pytest.mark.asyncio
async def test_brand_score_full_integration(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Score Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Performance")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

        # Write GSC findings (crawl errors = 4 => organic_score = 100 - 4*15 = 40)
        s.add(BrandProperty(
            tenant_id=tenant_id,
            brand_id=brand_id,
            type="search_console",
            status="degraded",
            provider="google",
            findings={"crawl_errors": 4, "warnings": []}
        ))

        # Write GMC findings (disapproved = 3 => gmc_score = 100 - 3*10 = 70)
        s.add(BrandProperty(
            tenant_id=tenant_id,
            brand_id=brand_id,
            type="merchant_feed",
            status="degraded",
            provider="google",
            findings={"disapproved_products": 3, "active_items": 100}
        ))

        # Write Brand mentions (count = 450 => pr_score = (450/1000)*100 = 45)
        s.add(BrandProperty(
            tenant_id=tenant_id,
            brand_id=brand_id,
            type="brand_mentions",
            status="healthy",
            provider="manual",
            findings={"mentions_count": 450}
        ))

        # Write Campaign and POAS/Paid spend details
        # Campaign 1: Spend = 1000 INR, Clicks = 100, Orders = 3
        # Gross revenue = 3 * 500 = 1500 INR
        # COGS = 3 * 200 = 600 INR
        # Margin = 1500 - 600 = 900 INR. POAS = 900 / 1000 = 0.90
        campaign = Campaign(id="camp_score_1", tenant_id=tenant_id, brand_id=brand_id, name="Score Promo", platform="meta", status="active")
        s.add(campaign)
        await s.commit()
        camp_id = campaign.id

        s.add(SpendFact(tenant_id=tenant_id, campaign_id=camp_id, amount_minor=1000_00, date=dt.date.today()))
        
        # Add 100 clicks touchpoints, and 3 orders
        for i in range(100):
            s.add(Touchpoint(tenant_id=tenant_id, campaign_id=camp_id, customer_id=f"cust_{i}", type="click", occurred_at=dt.datetime.now()))
        
        for i in range(3):
            order = Order(tenant_id=tenant_id, brand_id=brand_id, customer_id=f"cust_{i}", placed_at=dt.datetime.now(), amount_minor=500_00, currency="INR")
            s.add(order)
            await s.commit()
            
            ol = OrderLine(tenant_id=tenant_id, order_id=order.id, qty=1, unit_price_minor=500_00, line_discount_minor=0, unit_cost_minor=200_00)
            s.add(ol)
            
            fc = FulfillmentCost(tenant_id=tenant_id, order_id=order.id, shipping_cost_minor=0, marketplace_fee_minor=0)
            s.add(fc)
            
            # Click occurred slightly before order placement to attribute
            tp = Touchpoint(tenant_id=tenant_id, campaign_id=camp_id, customer_id=f"cust_{i}", type="click", occurred_at=dt.datetime.now() - dt.timedelta(minutes=5))
            s.add(tp)
            
        await s.commit()

    H = {"X-Tenant-ID": tenant_id}

    # Fetch performance metric
    resp = await client.get(
        f"/metrics/brand-performance?brand_id={brand_id}&w_ux=4&w_organic=3&w_paid=2&w_pr=1",
        headers=H
    )
    assert resp.status_code == 200
    data = resp.json()

    # Weight sums: 4 + 3 + 2 + 1 = 10
    # w_ux = 0.40, w_organic = 0.30, w_paid = 0.20, w_pr = 0.10
    assert data["weights"]["ux"] == 0.40
    assert data["weights"]["organic"] == 0.30
    assert data["weights"]["paid"] == 0.20
    assert data["weights"]["pr"] == 0.10

    # Organic: 4 errors => score = 40.0
    assert data["components"]["organic"]["score"] == 40.0

    # PR: 450 mentions => score = 45.0
    assert data["components"]["pr"]["score"] == 45.0

    # Paid spend = 1000_00, Margin = 900_00 => POAS = 0.90
    # Paid score = (POAS / 2.0) * 100 = (0.90 / 2.0) * 100 = 45.0
    assert data["components"]["paid"]["score"] == 45.0

    # UX: CR + GMC health
    # Total clicks = 103 (100 base + 3 attribution clicks)
    # Total orders = 3 => CR = 3 / 103 = 0.0291
    # CR score = (0.0291 / 0.05) * 100 = 58.25
    # GMC score = 100 - 3*10 = 70.0
    # Average UX = (58.25 + 70.0) / 2 = 64.12
    assert 64.0 <= data["components"]["ux"]["score"] <= 65.0


@pytest.mark.asyncio
async def test_brand_score_partial_missing_data(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # Bootstrap Tenant and Brand with zero properties or orders
    async with async_session() as s:
        tenant = Tenant(name="Score Tenant Empty", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Empty")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    resp = await client.get(
        f"/metrics/brand-performance?brand_id={brand_id}",
        headers=H
    )
    assert resp.status_code == 200
    data = resp.json()

    # All missing properties default to 100.0, so composite should be 100.0
    assert data["composite_b_score"] == 100.0
    assert data["components"]["ux"]["score"] == 100.0
    assert data["components"]["organic"]["score"] == 100.0
    assert data["components"]["paid"]["score"] == 100.0
    assert data["components"]["pr"]["score"] == 100.0


def test_brand_score_non_gating_proof():
    """Verify that calculate_brand_performance_score is never imported or called in loop.py or services.py gates."""
    import ast
    
    files_to_check = [
        "app/kernel/loop.py",
        "app/kernel/services.py"
    ]
    
    for filepath in files_to_check:
        with open(filepath, "r") as f:
            tree = ast.parse(f.read(), filename=filepath)
            
        # Scan for imports or references to brand score calculations
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert "brand_score" not in name.name, f"Forbidden import of brand_score in {filepath}"
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "brand_score" not in node.module, f"Forbidden import of brand_score in {filepath}"
                for name in node.names:
                    assert name.name != "calculate_brand_performance_score", f"Forbidden import of calculate_brand_performance_score in {filepath}"
            elif isinstance(node, ast.Name):
                assert node.id != "calculate_brand_performance_score", f"Forbidden reference to calculate_brand_performance_score in {filepath}"

