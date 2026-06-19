import pytest
import datetime as dt
from sqlalchemy import select
from app.kernel import loop
from app.kernel.services import compute_snapshots, resolve_brand_tier
from app.kernel.optypes import OpState
from app.models import Tenant, Brand, TrustSnapshot, TrustEvent, AuditEvent, OpRow, OutboxItem
from app.services.marketing import MockMarketingClient
from app.adapters.grow import GrowAdapter

@pytest.fixture(scope="module", autouse=True)
def register_adapters():
    """Ensure GrowAdapter is registered for the duration of these tests."""
    loop.register(GrowAdapter())


@pytest.fixture(autouse=True)
def clean_mock_campaigns():
    """Clear mock clients before and after each test."""
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()


@pytest.fixture
async def setup_brand(session):
    """Set up a clean tenant and brand in the database."""
    tenant = Tenant(id="t_trust", name="Trust Tenant", hosting_tier="shared")
    brand = Brand(id="b_trust", tenant_id="t_trust", name="Trust Brand")
    session.add(tenant)
    session.add(brand)
    await session.commit()
    return tenant, brand


@pytest.mark.asyncio
async def test_compute_snapshots_tier_elevation(session, setup_brand):
    """Verify that a brand's tier is dynamically elevated on positive events, logging an audit event."""
    tenant, brand = setup_brand
    now = dt.datetime.now(dt.timezone.utc)

    # 1. Establish baseline at Tier 1 (supervised)
    baseline = TrustSnapshot(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        score=75.0,  # Tier 1 (60.0 <= score < 85.0)
        tier=1,
        ts=now - dt.timedelta(days=2)
    )
    session.add(baseline)
    await session.commit()

    # Verify baseline tier
    t_base = await resolve_brand_tier(session, tenant.id, brand.id, "grow")
    assert t_base == 1

    # 2. Emit positive trust events (verified_success)
    # The default history weight for verified_success is +1.0.
    # Base health score is 67.0 (20 GTM + 20 Pixel + 27 CAPI).
    # To exceed the 85.0 threshold for Tier 2, we need history to add at least 18.0.
    # Let's emit 20 events, which gives a history contribution of +20.0.
    for i in range(20):
        event = TrustEvent(
            tenant_id=tenant.id,
            brand_id=brand.id,
            domain="grow",
            kind="verified_success",
            base_delta=1.0,
            ts=now - dt.timedelta(hours=1)
        )
        session.add(event)
    await session.commit()

    # 3. Compute snapshots
    await compute_snapshots(session, now=now)
    await session.commit()

    # 4. Verify elevation to Tier 2 (autonomous)
    t_new = await resolve_brand_tier(session, tenant.id, brand.id, "grow")
    assert t_new == 2

    # 5. Assert that a 'trust.tier_elevated' audit event was logged in the ledger
    stmt = select(AuditEvent).where(
        AuditEvent.tenant_id == tenant.id,
        AuditEvent.action == "trust.tier_elevated"
    )
    res = await session.execute(stmt)
    audit = res.scalar_one_or_none()
    assert audit is not None
    assert audit.payload["old_tier"] == 1
    assert audit.payload["new_tier"] == 2
    assert audit.payload["domain"] == "grow"
    assert audit.payload["score"] >= 85.0


@pytest.mark.asyncio
async def test_compute_snapshots_tier_demotion_and_alerting(session, setup_brand):
    """Verify that a brand's tier is demoted on negative events, logging an audit event and dispatching an alert Op."""
    tenant, brand = setup_brand
    now = dt.datetime.now(dt.timezone.utc)

    # 1. Establish baseline at Tier 2 (autonomous)
    baseline = TrustSnapshot(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        score=90.0,  # Tier 2 (score >= 85.0)
        tier=2,
        ts=now - dt.timedelta(days=2)
    )
    session.add(baseline)
    await session.commit()

    t_base = await resolve_brand_tier(session, tenant.id, brand.id, "grow")
    assert t_base == 2

    # 2. Emit a negative trust event (override)
    # The default history weight for override is -5.0.
    # Base health score is 67.0.
    # Total score = 67.0 - 5.0 = 62.0.
    # Since 60.0 <= 62.0 < 85.0, this demotes the brand to Tier 1!
    event = TrustEvent(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        kind="override",
        base_delta=-5.0,
        ts=now - dt.timedelta(hours=1)
    )
    session.add(event)
    await session.commit()

    # 3. Compute snapshots
    await compute_snapshots(session, now=now)
    await session.commit()

    # 4. Verify demotion to Tier 1 (supervised)
    t_new = await resolve_brand_tier(session, tenant.id, brand.id, "grow")
    assert t_new == 1

    # 5. Assert that a 'trust.tier_demoted' audit event was logged in the ledger
    stmt_audit = select(AuditEvent).where(
        AuditEvent.tenant_id == tenant.id,
        AuditEvent.action == "trust.tier_demoted"
    )
    res_audit = await session.execute(stmt_audit)
    audit = res_audit.scalar_one_or_none()
    assert audit is not None
    assert audit.payload["old_tier"] == 2
    assert audit.payload["new_tier"] == 1
    assert audit.payload["score"] < 85.0

    # 6. Assert that a grow.alert.dispatch Op was AUTOMATICALLY proposed, auto-approved, and enqueued!
    stmt_op = select(OpRow).where(
        OpRow.tenant_id == tenant.id,
        OpRow.action == "grow.alert.dispatch"
    )
    res_op = await session.execute(stmt_op)
    op = res_op.scalar_one_or_none()
    assert op is not None
    assert op.state == OpState.APPROVED.value  # Must be auto-approved!
    assert "DEMOTED from Tier 2 to Tier 1" in op.params["message"]

    # Verify it was enqueued in the outbox for async delivery
    stmt_outbox = select(OutboxItem).where(OutboxItem.op_id == op.id)
    res_outbox = await session.execute(stmt_outbox)
    outbox = res_outbox.scalar_one_or_none()
    assert outbox is not None
    assert outbox.status == "PENDING"


@pytest.mark.asyncio
async def test_compute_snapshots_lockout_tier(session, setup_brand):
    """Verify that severe trust drops trigger a demotion to Tier 0 (Lockout) and dispatch a critical lockout alert."""
    tenant, brand = setup_brand
    now = dt.datetime.now(dt.timezone.utc)

    # 1. Establish baseline at Tier 2 (autonomous)
    baseline = TrustSnapshot(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        score=90.0,
        tier=2,
        ts=now - dt.timedelta(days=2)
    )
    session.add(baseline)
    await session.commit()

    # 2. Emit massive negative trust events (e.g. multiple failures driving score below 60.0)
    for i in range(5):
        event = TrustEvent(
            tenant_id=tenant.id,
            brand_id=brand.id,
            domain="grow",
            kind="verify_failure",
            base_delta=-8.0,
            ts=now - dt.timedelta(hours=1)
        )
        session.add(event)
    await session.commit()

    # 3. Compute snapshots
    await compute_snapshots(session, now=now)
    await session.commit()

    # 4. Verify demotion to Tier 0 (Lockout)
    # Score drops below 60.0 -> Tier 0!
    t_new = await resolve_brand_tier(session, tenant.id, brand.id, "grow")
    assert t_new == 0

    # 5. Assert that a 'trust.tier_demoted' audit event was logged
    stmt_audit = select(AuditEvent).where(
        AuditEvent.tenant_id == tenant.id,
        AuditEvent.action == "trust.tier_demoted"
    )
    res_audit = await session.execute(stmt_audit)
    audit = res_audit.scalar_one_or_none()
    assert audit is not None
    assert audit.payload["old_tier"] == 2
    assert audit.payload["new_tier"] == 0

    # 6. Assert that a critical lockout alert Op was proposed and auto-approved
    stmt_op = select(OpRow).where(
        OpRow.tenant_id == tenant.id,
        OpRow.action == "grow.alert.dispatch"
    )
    res_op = await session.execute(stmt_op)
    op = res_op.scalar_one_or_none()
    assert op is not None
    assert op.state == OpState.APPROVED.value
    assert "LOCKED OUT (Tier 0)" in op.params["message"]
    assert op.params["severity"] == "CRITICAL"
