import pytest
from sqlalchemy import select
from app.adapters.grow import GrowAdapter
from app.services.marketing import MockMarketingClient
from app.models import Campaign

@pytest.fixture(autouse=True)
def clean_mock_client():
    # Ensure mock client starts fresh for each test
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()

@pytest.fixture
def adapter():
    return GrowAdapter()

@pytest.mark.asyncio
async def test_grow_campaign_lifecycle_db_sync(adapter, session):
    # 1. Plan campaign creation
    intent = "create campaign winter-sale budget 1000 bid 10"
    ops = adapter.plan(intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    
    campaign_id = op.params["campaign_id"]
    assert campaign_id.startswith("camp-b1-")
    
    # 2. Execute creation
    res = await adapter.execute(op, "idem_create_campaign_123", session=session)
    assert res.ok is True
    
    # Assert persistent mock client has it
    client = MockMarketingClient(provider="google-ads")
    camp_external = await client.get_campaign(campaign_id)
    assert camp_external is not None
    assert camp_external["name"] == "winter-sale"
    assert camp_external["budget_minor"] == 100000 # 1000 INR * 100
    assert camp_external["status"] == "ACTIVE"
    
    # Assert local DB has it
    stmt = select(Campaign).where(Campaign.id == campaign_id)
    db_res = await session.execute(stmt)
    camp_db = db_res.scalar_one_or_none()
    assert camp_db is not None
    assert camp_db.name == "winter-sale"
    assert camp_db.status == "active"
    assert camp_db.platform == "google-ads"
    
    # 3. Verify
    verdict = await adapter.verify(op, session=session)
    assert verdict.ok is True
    assert verdict.checks["campaign_active"] is True
    
    # 4. Plan and execute Pause
    pause_intent = f"pause campaign {campaign_id}"
    pause_ops = adapter.plan(pause_intent, "t1", "b1")
    assert len(pause_ops) == 1
    pause_op = pause_ops[0]
    
    res_pause = await adapter.execute(pause_op, "idem_pause_123", session=session)
    assert res_pause.ok is True
    
    # Assert external is paused
    camp_ext_paused = await client.get_campaign(campaign_id)
    assert camp_ext_paused["status"] == "PAUSED"
    
    # Assert local DB is paused
    db_res = await session.execute(stmt)
    camp_db_paused = db_res.scalar_one_or_none()
    assert camp_db_paused.status == "paused"
    
    # 5. Plan and execute Resume
    resume_intent = f"resume campaign {campaign_id}"
    resume_ops = adapter.plan(resume_intent, "t1", "b1")
    assert len(resume_ops) == 1
    resume_op = resume_ops[0]
    
    res_resume = await adapter.execute(resume_op, "idem_resume_123", session=session)
    assert res_resume.ok is True
    
    # Assert external is active
    camp_ext_res = await client.get_campaign(campaign_id)
    assert camp_ext_res["status"] == "ACTIVE"
    
    # Assert local DB is active
    db_res = await session.execute(stmt)
    camp_db_res = db_res.scalar_one_or_none()
    assert camp_db_res.status == "active"
    
    # 6. Execute Delete (via compensation of create)
    compensations = adapter.compensate(op)
    assert len(compensations) == 1
    delete_op = compensations[0]
    
    res_del = await adapter.execute(delete_op, "idem_delete_123", session=session)
    assert res_del.ok is True
    
    # Assert external is gone
    assert await client.get_campaign(campaign_id) is None
    
    # Assert local DB is gone
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None
