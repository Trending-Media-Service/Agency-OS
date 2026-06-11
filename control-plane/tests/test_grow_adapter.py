import pytest
import asyncio
from app.adapters.grow import GrowAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.services.marketing import MockMarketingClient

@pytest.fixture
def adapter():
    return GrowAdapter()

@pytest.fixture(autouse=True)
def clear_marketing_client():
    MockMarketingClient.clear()
    yield
    MockMarketingClient.clear()

@pytest.fixture
def create_intent():
    return "create ad campaign SummerSale budget 10000 bid 150"

@pytest.fixture
def create_op(adapter, create_intent):
    ops = adapter.plan(create_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_grow_adapter_plan(adapter, create_intent):
    ops = adapter.plan(create_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "grow.campaign.create"
    assert op.params["name"] == "summersale"
    assert op.params["budget_minor"] == 1000000
    assert op.params["bid_minor"] == 15000
    assert op.params["campaign_id"] == "camp-b1-summersale"

def test_grow_adapter_preview(adapter, create_op):
    preview_art = adapter.preview(create_op)
    assert preview_art.kind == "campaign_create_preview"
    assert "summersale" in preview_art.summary
    assert "10000.00 INR" in preview_art.summary
    assert "150.00 INR" in preview_art.summary

async def test_grow_adapter_execute_create(adapter, create_op):
    res = await adapter.execute(create_op, "idem_create_123")
    assert res.ok is True
    assert res.detail["campaign_id"] == "camp-b1-summersale"
    
    client = MockMarketingClient()
    camp = await client.get_campaign("camp-b1-summersale")
    assert camp is not None
    assert camp["name"] == "summersale"
    assert camp["budget_minor"] == 1000000

@pytest.mark.asyncio
async def test_grow_adapter_verify(adapter, create_op):
    client = MockMarketingClient()
    await client.create_campaign("camp-b1-summersale", "summersale", 1000000, 15000)

    verdict = await adapter.verify(create_op)
    assert verdict.ok is True
    assert verdict.checks["campaign_active"] is True

def test_grow_adapter_compensate(adapter, create_op):
    compensations = adapter.compensate(create_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "grow.campaign.delete"
    assert comp.params["campaign_id"] == "camp-b1-summersale"

async def test_grow_adapter_execute_delete(adapter, create_op):
    client = MockMarketingClient()
    await client.create_campaign("camp-b1-summersale", "summersale", 1000000, 15000)
    
    compensations = adapter.compensate(create_op)
    delete_op = compensations[0]
    
    res = await adapter.execute(delete_op, "idem_delete_123")
    assert res.ok is True
    
    camp = await client.get_campaign("camp-b1-summersale")
    assert camp is None
