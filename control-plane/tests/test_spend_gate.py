import pytest
import os
from sqlalchemy import select
from app.kernel import loop
from app.kernel.optypes import OpSpec, Severity, Reversibility, OpState
from app.models import OpRow, Tenant, Brand, Campaign, TrustSnapshot
from app.services.marketing import MockMarketingClient
from app.adapters.grow import GrowAdapter

@pytest.fixture(scope="module", autouse=True)
def register_adapters():
    """Ensure the GrowAdapter is registered for the duration of these tests."""
    loop.register(GrowAdapter())


@pytest.fixture(autouse=True)
def clean_mock_campaigns():
    """Ensure mock marketing campaigns are cleared before and after each test."""
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()


@pytest.fixture
async def setup_tenant_brand(session):
    """Create a tenant and brand in the DB for RLS and foreign keys."""
    tenant = Tenant(id="t_spend", name="Spend Tenant", hosting_tier="shared")
    brand = Brand(id="b_spend", tenant_id="t_spend", name="Spend Brand")
    session.add(tenant)
    session.add(brand)
    await session.commit()
    return tenant, brand


@pytest.mark.asyncio
async def test_spend_gate_under_cap_auto_approved(session, setup_tenant_brand):
    """Verify that a campaign creation under the spend cap is auto-approved in Tier-2."""
    tenant, brand = setup_tenant_brand

    # Set brand to Tier 2 (Autonomous)
    snapshot = TrustSnapshot(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        score=90.0,  # > 85.0 triggers Tier 2
        tier=2
    )
    session.add(snapshot)
    await session.commit()

    # Budget of 5,000 INR (cap is 10,000 INR)
    spec = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={"campaign_id": "c-under-cap", "name": "under-cap", "budget_minor": 500_000, "bid_minor": 5_000},
        severity=Severity(2, Reversibility.COMPENSATABLE)
    )

    row = await loop.propose(session, spec, actor="test")
    assert row.state == OpState.PROPOSED.value

    gate, requirement = await loop.preview_and_gate(session, row, tier=2, actor="test")

    # Under cap, no violations -> should be AUTO-approved!
    assert requirement == "AUTO"
    assert row.state == OpState.APPROVED.value
    assert not gate.blocked
    assert len(gate.violations) == 0


@pytest.mark.asyncio
async def test_spend_gate_over_cap_requires_human(session, setup_tenant_brand):
    """Verify that a campaign creation over the spend cap requires HUMAN approval in Tier-2."""
    tenant, brand = setup_tenant_brand

    # Set brand to Tier 2 (Autonomous)
    snapshot = TrustSnapshot(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        score=90.0,
        tier=2
    )
    session.add(snapshot)
    await session.commit()

    # Budget of 15,000 INR (cap is 10,000 INR)
    spec = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={"campaign_id": "c-over-cap", "name": "over-cap", "budget_minor": 1_500_000, "bid_minor": 5_000},
        severity=Severity(2, Reversibility.COMPENSATABLE)
    )

    row = await loop.propose(session, spec, actor="test")
    assert row.state == OpState.PROPOSED.value

    gate, requirement = await loop.preview_and_gate(session, row, tier=2, actor="test")

    # Over cap -> should require HUMAN approval, not blocked completely!
    assert requirement == "HUMAN"
    assert row.state == OpState.AWAITING_APPROVAL.value
    assert not gate.blocked
    assert len(gate.violations) == 1
    
    violation = gate.violations[0]
    assert violation.rule_id == "grow_campaign_budget_cap"
    assert "exceeds" in violation.message.lower()


@pytest.mark.asyncio
async def test_dry_run_execution_safety(session, setup_tenant_brand):
    """Verify that dry_run=True skips external API calls and local DB writes."""
    tenant, brand = setup_tenant_brand
    adapter = GrowAdapter()

    # 1. Propose and execute a campaign with dry_run=True
    spec_dry = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={
            "campaign_id": "c-dry-run-test",
            "name": "dry-run-test",
            "budget_minor": 500_000,
            "bid_minor": 5_000,
            "dry_run": True,
            "provider": "mock"
        },
        severity=Severity(2, Reversibility.COMPENSATABLE)
    )

    # Execute directly via adapter
    res = await adapter.execute(spec_dry, idem_key="idem-dry", session=session)
    assert res.ok
    assert res.detail.get("dry_run") is True

    # VERIFICATION 1: The campaign must NOT exist in the external mock client!
    external_campaigns = MockMarketingClient._load()
    assert "c-dry-run-test" not in external_campaigns

    # VERIFICATION 2: The campaign must NOT exist in the local database!
    stmt = select(Campaign).where(Campaign.id == "c-dry-run-test")
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_real_execution_side_effects(session, setup_tenant_brand):
    """Verify that dry_run=False (default) performs external API calls and local DB writes."""
    tenant, brand = setup_tenant_brand
    adapter = GrowAdapter()

    # 2. Propose and execute a campaign with dry_run=False
    spec_real = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={
            "campaign_id": "c-real-test",
            "name": "real-test",
            "budget_minor": 500_000,
            "bid_minor": 5_000,
            "dry_run": False,
            "provider": "mock"
        },
        severity=Severity(2, Reversibility.COMPENSATABLE)
    )

    res = await adapter.execute(spec_real, idem_key="idem-real", session=session)
    assert res.ok
    assert "dry_run" not in res.detail

    # VERIFICATION 1: The campaign MUST exist in the external mock client!
    external_campaigns = MockMarketingClient._load()
    assert "c-real-test" in external_campaigns
    assert external_campaigns["c-real-test"]["budget_minor"] == 500_000

    # VERIFICATION 2: The campaign MUST exist in the local database!
    stmt = select(Campaign).where(Campaign.id == "c-real-test")
    db_res = await session.execute(stmt)
    db_camp = db_res.scalar_one_or_none()
    assert db_camp is not None
    assert db_camp.name == "real-test"
