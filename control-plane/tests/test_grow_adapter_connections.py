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
