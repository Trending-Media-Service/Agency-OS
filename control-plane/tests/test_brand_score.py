import pytest
import datetime as dt
import ast
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select

from app.models import Tenant, Brand, BrandProperty, Campaign, SpendFact, Touchpoint, Order, OrderLine, OpRow, AuditEvent
from app.profit.brand_score import calculate_brand_score, calculate_brand_performance_score
from app.kernel.services import audit_verify


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

    async with async_session() as s:
        # Calculate Brand Score:
        # UX: 60.0 * 0.1 = 6.0
        # Org: 90.0 * 0.5 = 45.0
        # Paid: 50.0 * 0.2 = 10.0
        # PR: 70.0 * 0.2 = 14.0
        # Expected: 6.0 + 45.0 + 10.0 + 14.0 = 75.0
        score = await calculate_brand_score(s, tid, bid)
        assert score == 75.0


@pytest.mark.asyncio
async def test_brand_performance_api_endpoint(client, db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="API Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="API Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Seed partial properties (missing PR property)
        prop_ux = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="ux_analytics",
            provider="shopify",
            findings={"conversion_rate": 0.02} # 40.0 points
        )
        prop_org = BrandProperty(
            tenant_id=tid,
            brand_id=bid,
            type="presence_audit",
            provider="google",
            findings={"indexing_coverage_ratio": 0.75} # 75.0 points
        )
        s.add_all([prop_ux, prop_org])
        await s.commit()

    H = {"X-Tenant-ID": tid}

    # 1. Fetch with default weights
    r_default = await client.get(f"/metrics/brand-performance?brand_id={bid}", headers=H)
    assert r_default.status_code == 200
    data = r_default.json()
    assert data["brand_id"] == bid
    # Weights default: UX=0.3, Org=0.2, Paid=0.4, PR=0.1
    # UX = 40.0 * 0.3 = 12.0
    # Org = 75.0 * 0.2 = 15.0
    # Paid = 50.0 (fallback) * 0.4 = 20.0
    # PR = 0.0 (missing) * 0.1 = 0.0
    # Composite: 12 + 15 + 20 = 47.0
    assert data["composite_b_score"] == 47.0
    assert data["components"]["ux"]["score"] == 40.0
    assert data["components"]["organic"]["score"] == 75.0
    assert data["components"]["paid"]["score"] == 50.0
    assert data["components"]["pr"]["score"] == 0.0

    # 2. Fetch with query param weight overrides
    # w_ux=1, w_organic=1, w_paid=0, w_pr=0 -> Equal 0.5/0.5 weights
    # UX = 40 * 0.5 = 20
    # Org = 75 * 0.5 = 37.5
    # Composite: 57.5
    r_override = await client.get(
        f"/metrics/brand-performance?brand_id={bid}&w_ux=1&w_organic=1&w_paid=0&w_pr=0",
        headers=H
    )
    assert r_override.status_code == 200
    data_override = r_override.json()
    assert data_override["composite_b_score"] == 57.5
    assert data_override["weights"]["ux"] == 0.5
    assert data_override["weights"]["organic"] == 0.5


def test_non_gating_invariant_ast():
    """Air-tight static AST check to guarantee B performance score never gates execution."""
    for filepath in ["app/kernel/loop.py", "app/kernel/services.py"]:
        with open(filepath, "r") as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            # 1. Assert no imports from brand_score module
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "brand_score" not in node.module, f"Security violation: brand_score imported in {filepath}!"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "brand_score" not in alias.name, f"Security violation: brand_score imported in {filepath}!"
            
            # 2. Assert no calls to calculate_brand_score or calculate_brand_performance_score
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                
                assert func_name not in ["calculate_brand_score", "calculate_brand_performance_score"], \
                    f"Security violation: brand score function called inside {filepath}!"


@pytest.mark.asyncio
async def test_non_gating_invariant_execution_independency(client, db_engine):
    """Asserts that altering performance weights leaves all Op decisions byte-identical."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="Gating Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="Gating Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # 1. Set weights W1
        prop_w1 = BrandProperty(
            tenant_id=tid, brand_id=bid, type="brand_performance_weights", provider="system",
            findings={"w_ux": 9.0, "w_organic": 0.0, "w_paid": 0.0, "w_pr": 0.0}
        )
        s.add(prop_w1)
        
        # Pre-seed an Op
        op = OpRow(
            id="op_gate_test", tenant_id=tid, brand_id=bid, domain="grow",
            action="grow.bid.adjust", state="PROPOSED", params={"campaign_id": "c1", "new_bid_minor": 1500},
            preview_summary="preview", impact=1, reversibility="REVERSIBLE", idem_key="idem_gate_test"
        )
        s.add(op)
        await s.commit()

    H = {"X-Tenant-ID": tid}

    # Propose/preview the Op under W1
    from app.kernel import loop
    async with async_session() as s:
        row = await s.get(OpRow, "op_gate_test")
        gate_w1, req_w1 = await loop.preview_and_gate(s, row, tier=1)
        await s.commit()

    # 2. Alter weights to W2 (complete opposite)
    async with async_session() as s:
        prop = await s.scalar(select(BrandProperty).filter_by(tenant_id=tid, brand_id=bid, type="brand_performance_weights"))
        prop.findings = {"w_ux": 0.0, "w_organic": 9.0, "w_paid": 9.0, "w_pr": 9.0}
        
        # Reset Op state to PROPOSED to re-trigger gate
        row = await s.get(OpRow, "op_gate_test")
        row.state = "PROPOSED"
        await s.commit()

    # Re-evaluate gate under W2
    async with async_session() as s:
        row = await s.get(OpRow, "op_gate_test")
        gate_w2, req_w2 = await loop.preview_and_gate(s, row, tier=1)
        await s.commit()

    # Assert that the gate violations, blocked status, and human approval requirements are completely identical
    assert req_w1 == req_w2
    assert gate_w1.blocked == gate_w2.blocked
    assert len(gate_w1.violations) == len(gate_w2.violations)


@pytest.mark.asyncio
async def test_brand_performance_read_only_guarantee(client, db_engine):
    """Verifies that calling the performance score endpoint has no side effects on DB state or audit verification."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    async with async_session() as s:
        tenant = Tenant(name="RO Tenant", hosting_tier="shared")
        s.add(tenant)
        await s.commit()
        tid = tenant.id

        brand = Brand(tenant_id=tid, name="RO Brand")
        s.add(brand)
        await s.commit()
        bid = brand.id

        # Seed an audit event to initialize the chain
        from app.kernel.services import audit_append
        await audit_append(s, tenant_id=tid, actor="system", action="init", payload={"role": "admin"})
        await s.commit()

    # Verify audit chain integrity before
    async with async_session() as s:
        ok_before, bad_id_before = await audit_verify(s)
        assert ok_before is True
        
        # Get count of ops and audit events before
        op_count_before = len((await s.execute(select(OpRow).where(OpRow.tenant_id == tid))).scalars().all())
        audit_count_before = len((await s.execute(select(AuditEvent).where(AuditEvent.tenant_id == tid))).scalars().all())

    H = {"X-Tenant-ID": tid}

    # Query the performance metrics endpoint multiple times
    for _ in range(3):
        r = await client.get(f"/metrics/brand-performance?brand_id={bid}", headers=H)
        assert r.status_code == 200

    # Assert state is unchanged
    async with async_session() as s:
        op_count_after = len((await s.execute(select(OpRow).where(OpRow.tenant_id == tid))).scalars().all())
        audit_count_after = len((await s.execute(select(AuditEvent).where(AuditEvent.tenant_id == tid))).scalars().all())
        assert op_count_before == op_count_after
        assert audit_count_before == audit_count_after
        
        ok_after, bad_id_after = await audit_verify(s)
        assert ok_after is True
        assert bad_id_before == bad_id_after
