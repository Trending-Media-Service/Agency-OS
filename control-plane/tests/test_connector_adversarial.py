import pytest
from sqlalchemy import select
from app.models import Connection
from app.adapters.manage import ManageAdapter
from app.adapters.presence import PresenceAdapter
from app.adapters.grow import GrowAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.services.secrets import SecretManagerClient

pytestmark = pytest.mark.usefixtures("mock_secrets_client")

@pytest.fixture
def manage_adapter():
    return ManageAdapter()

@pytest.fixture
def presence_adapter():
    return PresenceAdapter()

@pytest.fixture
def grow_adapter():
    return GrowAdapter()

# 1. BOTH credential and secret_ref are present (prioritize credential)
@pytest.mark.asyncio
async def test_adversarial_both_keys_present_prioritize_credential(manage_adapter, session):
    op = OpSpec(
        tenant_id="t_adv_1",
        brand_id="b_adv_1",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "primary-credential-token",
            "secret_ref": "secondary-secret-ref-token",
            "config": {"shop_url": "adv1.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    
    res = await manage_adapter.execute(op, "idem_adv_1", session=session)
    assert res.ok is True
    
    # Query database to find the connection
    stmt = select(Connection).where(
        Connection.tenant_id == "t_adv_1",
        Connection.brand_id == "b_adv_1",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    # Read the secret value and verify it used 'credential'
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "primary-credential-token", "Should prioritize 'credential' over 'secret_ref'"


# 2. credential is empty/None but secret_ref is present (fallback to secret_ref)
@pytest.mark.asyncio
@pytest.mark.parametrize("empty_val", [None, ""])
async def test_adversarial_credential_empty_fallback_to_secret_ref(manage_adapter, session, empty_val):
    op = OpSpec(
        tenant_id="t_adv_2",
        brand_id="b_adv_2",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": empty_val,
            "secret_ref": "fallback-secret-ref-token",
            "config": {"shop_url": "adv2.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    
    res = await manage_adapter.execute(op, f"idem_adv_2_{empty_val}", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t_adv_2",
        Connection.brand_id == "b_adv_2",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "fallback-secret-ref-token", f"Should fall back to 'secret_ref' when 'credential' is {empty_val}"


# 3. BOTH keys are missing or resolve to empty/None values
@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"provider": "shopify", "config": {"shop_url": "adv3.myshopify.com"}},
    {"provider": "shopify", "credential": None, "secret_ref": None, "config": {"shop_url": "adv3.myshopify.com"}},
    {"provider": "shopify", "credential": "", "secret_ref": "", "config": {"shop_url": "adv3.myshopify.com"}},
])
async def test_adversarial_both_keys_missing_or_empty(manage_adapter, session, params):
    op = OpSpec(
        tenant_id="t_adv_3",
        brand_id="b_adv_3",
        domain="manage",
        action="manage.shopify.connect",
        params=params,
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    
    # We want to see how the adapter behaves when credentials are empty/missing.
    # Ideally, establishing a connection without any credential should fail.
    # Let's run execute and check the behavior.
    try:
        res = await manage_adapter.execute(op, "idem_adv_3", session=session)
        # If it returns success but creates a connection with None/empty credential, that's a security/logic bug!
        if res.ok:
            stmt = select(Connection).where(
                Connection.tenant_id == "t_adv_3",
                Connection.brand_id == "b_adv_3",
                Connection.provider == "shopify"
            )
            db_res = await session.execute(stmt)
            conn = db_res.scalar_one_or_none()
            
            # Check what's in Secret Manager
            if conn and conn.credential:
                secrets_client = SecretManagerClient()
                val = None
                try:
                    val = await secrets_client.read_secret(conn.credential)
                except ValueError:
                    # Secret not found is treated as None
                    pass
                
                assert val not in (None, ""), f"Connection should not have None or empty secret in Secret Manager (got: {val})"
    except Exception as e:
        # If it raised an exception, that's a failure mode we want to document.
        pytest.fail(f"Execution raised unexpected exception: {e}")


# 4. Extremely long tokens, special characters, or malformed payloads
@pytest.mark.asyncio
async def test_adversarial_extremely_long_and_special_char_tokens(manage_adapter, session):
    # Token containing non-ASCII, emojis, quotes, control characters, and extremely long length (10KB)
    special_token = "🔑-§pécial-ch@r-“quote”-newline\n-tab\t-" + ("A" * 10000)
    
    op = OpSpec(
        tenant_id="t_adv_4",
        brand_id="b_adv_4",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": special_token,
            "config": {"shop_url": "adv4.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    
    res = await manage_adapter.execute(op, "idem_adv_4", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t_adv_4",
        Connection.brand_id == "b_adv_4",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    # DB column 'credential' stores the Secret Manager path, which must be within 255 chars
    assert len(conn.credential) <= 255, "Connection.credential column must not exceed 255 chars"
    
    # Read the secret value and verify it was preserved exactly
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == special_token, "Special/long token must be stored and retrieved exactly"


# 5. Multiple consecutive execution requests (idempotency & updates)
@pytest.mark.asyncio
async def test_adversarial_idempotency_consecutive_execution(manage_adapter, session):
    # Call 1: Connect shopify with token 1
    op1 = OpSpec(
        tenant_id="t_adv_5",
        brand_id="b_adv_5",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "token-1",
            "config": {"shop_url": "adv5.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    res1 = await manage_adapter.execute(op1, "idem_adv_5_1", session=session)
    assert res1.ok is True
    
    # Verify DB has exactly one connection
    stmt = select(Connection).where(
        Connection.tenant_id == "t_adv_5",
        Connection.brand_id == "b_adv_5",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conns = db_res.scalars().all()
    assert len(conns) == 1
    
    # Call 2: Connect again with different token and same idem key (or different)
    op2 = OpSpec(
        tenant_id="t_adv_5",
        brand_id="b_adv_5",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "token-2",
            "config": {"shop_url": "adv5.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    res2 = await manage_adapter.execute(op2, "idem_adv_5_2", session=session)
    assert res2.ok is True
    
    # Verify DB still has exactly one connection (updated)
    db_res = await session.execute(stmt)
    conns = db_res.scalars().all()
    assert len(conns) == 1
    
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conns[0].credential)
    assert val == "token-2", "Consecutive execution must update connection credential to the latest value"
    
    # Call 3: Disconnect
    op_disc = OpSpec(
        tenant_id="t_adv_5",
        brand_id="b_adv_5",
        domain="manage",
        action="manage.shopify.disconnect",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
    )
    res_disc1 = await manage_adapter.execute(op_disc, "idem_adv_5_disc1", session=session)
    assert res_disc1.ok is True
    
    # Verify DB has 0 connections
    db_res = await session.execute(stmt)
    conns = db_res.scalars().all()
    assert len(conns) == 0
    
    # Call 4: Disconnect again (idempotent no-op)
    res_disc2 = await manage_adapter.execute(op_disc, "idem_adv_5_disc2", session=session)
    assert res_disc2.ok is True
