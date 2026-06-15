import pytest
import ast
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import Tenant, Brand, BrandProperty, Campaign, SpendFact, Touchpoint, Order, OrderLine, FulfillmentCost, OpRow
import datetime as dt
from app.kernel import loop
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money, OpState

@pytest.mark.asyncio
async def test_meridian_calibration_flow(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 1. Bootstrap Tenant and Brand
    async with async_session() as s:
        tenant = Tenant(name="Meridian Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Calibration")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    H = {"X-Tenant-ID": tenant_id}

    # 2. Add Geo Experiment Data Property
    async with async_session() as s:
        geo_data = BrandProperty(
            tenant_id=tenant_id,
            brand_id=brand_id,
            type="geo_experiment_data",
            provider="manual-upload",
            status="active",
            findings={"incremental_roas": 1.62, "attributed_roas": 1.35} # alpha = 1.62 / 1.35 = 1.2
        )
        s.add(geo_data)
        await s.commit()

    # 3. Act: Trigger Calibrate Attribution batch task (bypasses RLS)
    resp_cal = await client.post("/tasks/calibrate-attribution")
    assert resp_cal.status_code == 200
    assert resp_cal.json()["calibrated_count"] >= 1

    # Verify attribution_multiplier property in DB
    async with async_session() as s:
        stmt = select(BrandProperty).where(
            BrandProperty.tenant_id == tenant_id,
            BrandProperty.brand_id == brand_id,
            BrandProperty.type == "attribution_multiplier"
        )
        res = await s.execute(stmt)
        mult = res.scalar_one()
        assert mult.status == "active"
        assert mult.findings["alpha_inc"] == 1.2

    # 4. Bootstrap Campaign, Spend, Touchpoint, and Order to check POAS calibration
    async with async_session() as s:
        campaign = Campaign(id="camp-cal-1", tenant_id=tenant_id, brand_id=brand_id, name="Google Ads Cal", platform="google-ads")
        s.add(campaign)
        await s.commit()
        
        spend = SpendFact(tenant_id=tenant_id, campaign_id="camp-cal-1", amount_minor=100_00, date=dt_date(2026, 6, 1))
        s.add(spend)
        
        now = dt.datetime.now(dt.timezone.utc)
        
        order = Order(tenant_id=tenant_id, brand_id=brand_id, amount_minor=150_00, customer_id="cust-1", placed_at=now)
        s.add(order)
        await s.commit()
        
        line = OrderLine(tenant_id=tenant_id, order_id=order.id, unit_price_minor=150_00, qty=1)
        s.add(line)
        
        # Touchpoint attributes order to campaign: occurred_at must be before placed_at
        tp = Touchpoint(tenant_id=tenant_id, customer_id="cust-1", campaign_id="camp-cal-1", type="click", occurred_at=now - dt.timedelta(minutes=5))
        s.add(tp)
        await s.commit()

    # Get POAS Report
    resp_poas = await client.get(f"/brands/{brand_id}/poas", headers=H)
    assert resp_poas.status_code == 200
    reports = resp_poas.json()["reports"]
    
    # We should have the campaign report calibrated by alpha_inc (1.2)
    # Attributed POAS = margin / spend. Margin = 150_00 (gross margin, cogs=0, fulfillment=0). Spend = 100_00.
    # Attributed POAS = 150_00 / 100_00 = 1.5
    # iPOAS = 1.5 * 1.2 = 1.80
    camp_report = [r for r in reports if r["campaign_id"] == "camp-cal-1"][0]
    assert camp_report["poas"] == 1.5
    assert camp_report["alpha_inc"] == 1.2
    assert camp_report["ipoas"] == 1.8


@pytest.mark.asyncio
async def test_alpha_driven_bid_exceeding_multiplier_blocked(client, db_engine):
    # Proposing a bid driven by alpha (e.g. attempting to adjust from 100 INR to 250 INR)
    # The new bid is 2.5x the previous bid, violating the 2x multiplier cap
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="Cap Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tenant_id = tenant.id

        brand = Brand(tenant_id=tenant_id, name="Tanmatra Cap")
        s.add(brand)
        await s.commit()
        brand_id = brand.id

    # Propose bid adjust Op
    op_spec = OpSpec(
        tenant_id=tenant_id,
        brand_id=brand_id,
        domain="grow",
        action="grow.bid.adjust",
        params={
            "campaign_id": "camp-test",
            "new_bid_minor": 25_000,      # ₹250
            "previous_bid_minor": 10_000   # ₹100
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(0)
    )

    async with async_session() as s:
        row = await loop.propose(s, op_spec, actor="optimizer")
        await s.commit()
        op_id = row.id

    # Run preview_and_gate - should block/require human because it is > 2x multiplier
    async with async_session() as s:
        db_row = await s.get(OpRow, op_id)
        gate, req = await loop.preview_and_gate(s, db_row, tier=2)
        await s.commit()
        
        # Since grow_bid_multiplier_cap is a blocking rule by default, req should be BLOCKED
        assert req == "BLOCKED"
        assert db_row.state == "BLOCKED"
        assert any("exceeds the 2x multiplier safety limit" in v.message for v in gate.violations)


def test_ast_check_calibration_isolation_proof():
    """Static AST verification proving the offline separation invariant:
    No stats/calibration modules (meridian, attribution) are ever imported
    or evaluated inside the critical path of the gate services or kernel loop.
    """
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Files defining the critical gate evaluation pathway
    critical_files = [
        os.path.join(base_dir, "app/kernel/services.py"),
        os.path.join(base_dir, "app/kernel/loop.py")
    ]
    
    forbidden_terms = ["meridian", "run_meridian_calibration", "attribution"]
    
    for fpath in critical_files:
        with open(fpath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=fpath)
            
        for node in ast.walk(tree):
            # 1. Assert no forbidden imports
            if isinstance(node, ast.Import):
                for name in node.names:
                    for term in forbidden_terms:
                        assert term not in name.name, f"Forbidden import of '{term}' in critical file {fpath}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for term in forbidden_terms:
                        assert term not in node.module, f"Forbidden import from '{term}' in critical file {fpath}"
                for name in node.names:
                    for term in forbidden_terms:
                        assert term not in name.name, f"Forbidden import from symbol '{term}' in critical file {fpath}"
                        
            # 2. Assert no dynamic call referencing calibration
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    for term in forbidden_terms:
                        assert node.func.id != term, f"Forbidden call to '{term}' inside critical file {fpath}"
                elif isinstance(node.func, ast.Attribute):
                    for term in forbidden_terms:
                        assert node.func.attr != term, f"Forbidden call to attribute '{term}' inside critical file {fpath}"


def dt_date(y, m, d):
    import datetime
    return datetime.date(y, m, d)
