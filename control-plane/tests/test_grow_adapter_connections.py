import pytest
from sqlalchemy import select
from app.adapters.grow import GrowAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Connection

@pytest.fixture
def adapter():
    return GrowAdapter()

# Google Ads Tests
@pytest.fixture
def google_connect_intent():
    return "connect google ads with secret:gads-secret-token"

@pytest.fixture
def google_connect_op(adapter, google_connect_intent):
    ops = adapter.plan(google_connect_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_grow_google_connect_plan(adapter, google_connect_intent):
    ops = adapter.plan(google_connect_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "grow.google.connect"
    assert op.params["provider"] == "google-ads"
    assert op.params["credential"] == "gads-secret-token"

def test_grow_google_connect_preview(adapter, google_connect_op):
    preview_art = adapter.preview(google_connect_op)
    assert preview_art.kind == "google_connect_preview"
    assert "****" in preview_art.summary

async def test_grow_google_connect_execute(adapter, google_connect_op, session):
    res = await adapter.execute(google_connect_op, "idem_gads_connect_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "google-ads"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.credential
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "gads-secret-token"

@pytest.mark.asyncio
async def test_grow_google_connect_verify(adapter, google_connect_op, session):
    await adapter.execute(google_connect_op, "idem_gads_verify_setup_123", session=session)
    verdict = await adapter.verify(google_connect_op, session=session)
    assert verdict.ok is True
    assert verdict.checks["api_token_valid"] is True
    assert verdict.checks["account_accessible"] is True

def test_grow_google_compensate(adapter, google_connect_op):
    compensations = adapter.compensate(google_connect_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "grow.google.disconnect"
    assert comp.params["provider"] == "google-ads"

async def test_grow_google_execute_disconnect(adapter, google_connect_op, session):
    # 1. Seed connection
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="google-ads",
        credential="gads-secret-token",
        config={}
    )
    session.add(conn)
    await session.commit()
    
    # 2. Compensate
    compensations = adapter.compensate(google_connect_op)
    disconnect_op = compensations[0]
    
    # 3. Execute disconnect
    res = await adapter.execute(disconnect_op, "idem_gads_disconnect_123", session=session)
    assert res.ok is True
    
    # 4. Verify gone
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "google-ads"
    )
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None


# Meta Ads Tests
@pytest.fixture
def meta_connect_intent():
    return "connect facebook ads with secret:meta-secret-token"

@pytest.fixture
def meta_connect_op(adapter, meta_connect_intent):
    ops = adapter.plan(meta_connect_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_grow_meta_connect_plan(adapter, meta_connect_intent):
    ops = adapter.plan(meta_connect_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "grow.meta.connect"
    assert op.params["provider"] == "meta-ads"
    assert op.params["credential"] == "meta-secret-token"

def test_grow_meta_connect_preview(adapter, meta_connect_op):
    preview_art = adapter.preview(meta_connect_op)
    assert preview_art.kind == "meta_connect_preview"
    assert "****" in preview_art.summary

async def test_grow_meta_connect_execute(adapter, meta_connect_op, session):
    res = await adapter.execute(meta_connect_op, "idem_meta_connect_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "meta-ads"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.credential
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "meta-secret-token"

@pytest.mark.asyncio
async def test_grow_meta_connect_verify(adapter, meta_connect_op, session):
    await adapter.execute(meta_connect_op, "idem_meta_verify_setup_123", session=session)
    verdict = await adapter.verify(meta_connect_op, session=session)
    assert verdict.ok is True
    assert verdict.checks["api_token_valid"] is True

def test_grow_meta_compensate(adapter, meta_connect_op):
    compensations = adapter.compensate(meta_connect_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "grow.meta.disconnect"
    assert comp.params["provider"] == "meta-ads"

async def test_grow_meta_execute_disconnect(adapter, meta_connect_op, session):
    # 1. Seed connection
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="meta-ads",
        credential="meta-secret-token",
        config={}
    )
    session.add(conn)
    await session.commit()
    
    # 2. Compensate
    compensations = adapter.compensate(meta_connect_op)
    disconnect_op = compensations[0]
    
    # 3. Execute disconnect
    res = await adapter.execute(disconnect_op, "idem_meta_disconnect_123", session=session)
    assert res.ok is True
    
    # 4. Verify gone
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "meta-ads"
    )
    db_res = await session.execute(stmt)
    assert db_res.scalar_one_or_none() is None

# Backward Compatibility Tests
@pytest.mark.asyncio
async def test_grow_google_connect_execute_backward_compatibility(adapter, session):
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="grow",
        action="grow.google.connect",
        params={
            "provider": "google-ads",
            "secret_ref": "legacy-gads-secret-token",
            "config": {}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(0)
    )
    res = await adapter.execute(op, "idem_gads_legacy_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "google-ads"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "legacy-gads-secret-token"


@pytest.mark.asyncio
async def test_grow_marketing_optimize_copy_integration(adapter, session):
    from app.models import BrandProperty, Connection
    from app.services.marketing import MockMarketingClient
    from app.services.secrets import SecretManagerClient
    
    MockMarketingClient.clear()
    
    # 1. Register the Google Ads token in the mock Secret Manager registry
    secrets_client = SecretManagerClient()
    credential_ref = await secrets_client.write_secret("t1-b1-google-ads-secret", "mock-gads-token-value")
    
    # 2. Seed the Google Ads Connection pointing to the registered secret
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="google-ads",
        credential=credential_ref,
        config={}
    )
    session.add(conn)
    
    # 3. Seed the Brand Identity (RAG) context
    rag_prop = BrandProperty(
        tenant_id="t1",
        brand_id="b1",
        type="brand_identity",
        provider="internal",
        status="active",
        findings={
            "tone_of_voice": "Energetic and clinical",
            "target_persona": "Orthopedic surgeons",
            "past_experience": "Avoid using 'cheap'"
        }
    )
    session.add(rag_prop)
    
    # 4. Seed the Tenant LoRA Adapter
    lora_prop = BrandProperty(
        tenant_id="t1",
        brand_id="b1",
        type="lora_adapter",
        provider="vertex-ai",
        status="active",
        findings={
            "endpoint_url": "https://us-central1-aiplatform.googleapis.com/v1/projects/mock-proj/locations/us-central1/endpoints/t1-lora"
        }
    )
    session.add(lora_prop)
    await session.commit()
    
    # 5. Create the target campaign in our mock Google Ads store
    client = MockMarketingClient()
    await client.create_campaign("camp-ableys-brand-search", "brand-search", 500000, 5000)
    
    # 5. Plan the optimize copy operation
    ops = adapter.plan("optimize ad copy for campaign camp-ableys-brand-search", "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "grow.marketing.optimize_copy"
    assert op.params["campaign_id"] == "camp-ableys-brand-search"
    
    # 6. Preview the operation
    preview_art = adapter.preview(op)
    assert preview_art.kind == "marketing_copy_optimize_preview"
    assert "Dynamic RAG Injection: YES" in preview_art.summary
    assert "Dynamic LoRA Adapter Routing: YES" in preview_art.summary
    
    # 7. Execute the operation (this will query DB RAG, LoRA, call LLM client, and update Google Ads!)
    res = await adapter.execute(op, "idem_optimize_123", session=session)
    assert res.ok is True
    assert "optimized_headline" in res.detail
    
    # 8. Verify the campaign's headline was programmatically mutated in Google Ads!
    camp = await client.get_campaign("camp-ableys-brand-search")
    assert camp is not None
    assert "headline" in camp
    assert "Energetic and clinical" in camp["headline"]

