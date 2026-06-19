import pytest
import logging
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from app.adapters.grow import GrowAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Campaign, Tenant, Brand
from app.services.marketing import MockMarketingClient

# Ensure logs are visible
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def cleanup_mock_marketing():
    """Clear the mock marketing campaign file before and after each test."""
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()


@pytest.fixture
async def setup_tenant_brand(session):
    """Create a tenant and brand in the DB for RLS and foreign keys."""
    tenant = Tenant(id="t1", name="Test Tenant", hosting_tier="shared")
    brand = Brand(id="b1", tenant_id="t1", name="Test Brand")
    session.add(tenant)
    session.add(brand)
    await session.commit()
    return tenant, brand


@pytest.mark.asyncio
async def test_grow_campaign_create_idempotency(session, setup_tenant_brand):
    """Verify that replaying a campaign creation Op does not double-execute the external client."""
    adapter = GrowAdapter()
    tenant, brand = setup_tenant_brand
    
    spec = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.create",
        params={
            "campaign_id": "camp-b1-test-idem",
            "name": "test-idem",
            "budget_minor": 100000,
            "bid_minor": 1000,
            "provider": "mock"  # Use mock provider to avoid connection/secret resolution
        },
        severity=Severity(2, Reversibility.COMPENSATABLE)
    )

    # We want to spy on MockMarketingClient's create_campaign method
    # Since MockMarketingClient is instantiated dynamically in execute(),
    # we patch the class method.
    with patch.object(MockMarketingClient, "create_campaign", side_effect=MockMarketingClient.create_campaign, autospec=True) as mock_create:
        
        # --- FIRST RUN ---
        logger.info("Starting Run 1")
        res1 = await adapter.execute(spec, idem_key=spec.idem_key, session=session)
        assert res1.ok
        assert mock_create.call_count == 1
        
        # Verify it wrote to local DB in this session
        stmt = select(Campaign).where(Campaign.id == "camp-b1-test-idem")
        db_res = await session.execute(stmt)
        assert db_res.scalar_one_or_none() is not None
        
        # --- SIMULATE ROLLBACK ---
        # We rollback the DB transaction to simulate a crash right after the external call
        # but before the DB transaction committed.
        logger.info("Simulating transaction rollback")
        await session.rollback()
        
        # Verify local DB state is rolled back (campaign is gone)
        db_res_post_rollback = await session.execute(stmt)
        assert db_res_post_rollback.scalar_one_or_none() is None
        
        # But the campaign STILL exists in the external system (MockMarketingClient's JSON file)
        # because the external call already completed!
        client = MockMarketingClient(provider="mock")
        ext_camp = await client.get_campaign("camp-b1-test-idem")
        assert ext_camp is not None
        assert ext_camp["status"] == "ACTIVE"
        
        # --- SECOND RUN (REPLAY) ---
        logger.info("Starting Run 2 (Replay)")
        # We run it again with the same session (which is now in a new transaction after rollback)
        res2 = await adapter.execute(spec, idem_key=spec.idem_key, session=session)
        assert res2.ok
        
        # CRITICAL ASSERTION: The external create_campaign should NOT have been called again!
        # If the adapter is idempotent, it should have detected the campaign already exists
        # and skipped the external call, while still registering it in the local DB.
        assert mock_create.call_count == 1, "MockMarketingClient.create_campaign was called twice! Double execution detected!"
        
        # Verify it successfully registered in the local DB on the second run
        db_res_run2 = await session.execute(stmt)
        assert db_res_run2.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_grow_campaign_delete_idempotency(session, setup_tenant_brand):
    """Verify that replaying a campaign deletion Op is idempotent and succeeds if already deleted."""
    adapter = GrowAdapter()
    tenant, brand = setup_tenant_brand
    
    # 1. Manually register a campaign in the external client and DB
    campaign_id = "camp-b1-delete-idem"
    client = MockMarketingClient(provider="mock")
    await client.create_campaign(campaign_id, "delete-idem", 100000, 1000)
    
    db_camp = Campaign(
        id=campaign_id,
        tenant_id=tenant.id,
        brand_id=brand.id,
        name="delete-idem",
        platform="mock",
        status="active"
    )
    session.add(db_camp)
    await session.commit()

    spec = OpSpec(
        tenant_id=tenant.id,
        brand_id=brand.id,
        domain="grow",
        action="grow.campaign.delete",
        params={
            "campaign_id": campaign_id,
            "provider": "mock"
        },
        severity=Severity(1, Reversibility.COMPENSATABLE)
    )

    with patch.object(MockMarketingClient, "delete_campaign", side_effect=MockMarketingClient.delete_campaign, autospec=True) as mock_delete:
        
        # --- FIRST RUN ---
        logger.info("Starting Delete Run 1")
        res1 = await adapter.execute(spec, idem_key=spec.idem_key, session=session)
        assert res1.ok
        assert mock_delete.call_count == 1
        
        # Verify it deleted from local DB
        stmt = select(Campaign).where(Campaign.id == campaign_id)
        db_res = await session.execute(stmt)
        assert db_res.scalar_one_or_none() is None
        
        # --- SIMULATE ROLLBACK OF DB ONLY ---
        # (This is a slightly different scenario: what if the DB delete rolled back, but external delete succeeded?
        # The campaign is gone externally, but STILL exists in local DB.
        # When we replay, it will try to delete it again!)
        logger.info("Simulating DB transaction rollback (restoring campaign in DB only)")
        # We manually re-add it to DB to simulate the rollback of the delete transaction
        session.add(Campaign(
            id=campaign_id,
            tenant_id=tenant.id,
            brand_id=brand.id,
            name="delete-idem",
            platform="mock",
            status="active"
        ))
        await session.commit()
        
        # Verify it is back in DB
        db_res_rollback = await session.execute(stmt)
        assert db_res_rollback.scalar_one_or_none() is not None
        
        # But it is GONE externally!
        ext_camp = await client.get_campaign(campaign_id)
        assert ext_camp is None
        
        # --- SECOND RUN (REPLAY) ---
        logger.info("Starting Delete Run 2 (Replay)")
        res2 = await adapter.execute(spec, idem_key=spec.idem_key, session=session)
        assert res2.ok
        
        # CRITICAL ASSERTION: The external delete_campaign should NOT have been called again!
        assert mock_delete.call_count == 1, "MockMarketingClient.delete_campaign was called twice!"
        
        # Verify it was successfully deleted from the local DB again
        db_res_run2 = await session.execute(stmt)
        assert db_res_run2.scalar_one_or_none() is None
