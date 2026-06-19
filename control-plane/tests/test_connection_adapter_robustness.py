import pytest
import pytest_asyncio
import datetime as dt
from sqlalchemy import select
from app.adapters.manage import ManageAdapter
from app.adapters.presence import PresenceAdapter
from app.adapters.grow import GrowAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Connection

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

# Test helper to construct standard OpSpec
def make_op_spec(domain: str, action: str, params: dict) -> OpSpec:
    return OpSpec(
        tenant_id="test-tenant",
        brand_id="test-brand",
        domain=domain,
        action=action,
        params=params,
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="USD")
    )

# --- Precedence Tests ---

async def test_precedence_both_keys_present_manage(session, mock_secrets_client):
    """Verify that 'credential' takes precedence over 'secret_ref' in ManageAdapter."""
    adapter = ManageAdapter()
    op = make_op_spec(
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "primary-credential-token",
            "secret_ref": "legacy-secret-ref-token",
            "config": {"shop_url": "test.myshopify.com"}
        }
    )
    
    res = await adapter.execute(op, "idem_prec_manage", session=session)
    assert res.ok is True
    
    # Check Connection in DB
    stmt = select(Connection).where(
        Connection.tenant_id == "test-tenant",
        Connection.brand_id == "test-brand",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    # Check value in mock secrets store
    assert conn.credential in mock_secrets_client.store
    secret_val = mock_secrets_client.store[conn.credential]
    assert secret_val == "primary-credential-token", "Credential did not take precedence over secret_ref"


async def test_precedence_both_keys_present_presence(session, mock_secrets_client):
    """Verify that 'credential' takes precedence over 'secret_ref' in PresenceAdapter."""
    adapter = PresenceAdapter()
    op = make_op_spec(
        domain="presence",
        action="presence.wordpress.connect",
        params={
            "provider": "wordpress",
            "credential": "wp-primary-credential",
            "secret_ref": "wp-legacy-secret-ref",
            "config": {"site_url": "test.wordpress.org"}
        }
    )
    
    res = await adapter.execute(op, "idem_prec_presence", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "test-tenant",
        Connection.brand_id == "test-brand",
        Connection.provider == "wordpress"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    assert conn.credential in mock_secrets_client.store
    secret_val = mock_secrets_client.store[conn.credential]
    assert secret_val == "wp-primary-credential", "Credential did not take precedence in PresenceAdapter"


async def test_precedence_both_keys_present_grow(session, mock_secrets_client):
    """Verify that 'credential' takes precedence over 'secret_ref' in GrowAdapter."""
    adapter = GrowAdapter()
    op = make_op_spec(
        domain="grow",
        action="grow.google.connect",
        params={
            "provider": "google",
            "credential": "google-primary-credential",
            "secret_ref": "google-legacy-secret-ref",
            "config": {"developer_token": "dev-token-123"}
        }
    )
    
    res = await adapter.execute(op, "idem_prec_grow", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "test-tenant",
        Connection.brand_id == "test-brand",
        Connection.provider == "google"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    assert conn.credential in mock_secrets_client.store
    secret_val = mock_secrets_client.store[conn.credential]
    assert secret_val == "google-primary-credential", "Credential did not take precedence in GrowAdapter"


# --- Missing / Empty / None Value Tests ---

async def test_both_keys_missing_or_none(session, mock_secrets_client):
    """Verify behavior when both keys are missing or None."""
    adapter = ManageAdapter()
    
    op_missing = make_op_spec(
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "config": {"shop_url": "test.myshopify.com"}
        }
    )
    
    res = await adapter.execute(op_missing, "idem_missing", session=session)
    assert res.ok is False
    assert "error" in res.detail


# --- Adversarial & Extreme Input Tests ---

async def test_extreme_and_adversarial_tokens(session, mock_secrets_client):
    """Test connection adapters with extremely long tokens, Unicode, SQL injection, and shell patterns."""
    adapter = ManageAdapter()
    
    # 1. Extremely long token (50KB)
    long_token = "A" * 50000
    
    # 2. Adversarial payload: SQL injection, shell injection, emojis, quotes, and newlines
    adversarial_token = (
        "'; DROP TABLE connections; -- \n"
        "$(rm -rf /)\n"
        "🚀🌟 Unicode Emojis & Special Chars: \u0000\u0007\b\t\n"
        "\"double_quotes\" 'single_quotes' `backticks` \\ backslash"
    )
    
    for token_type, token_val in [("long", long_token), ("adversarial", adversarial_token)]:
        op = make_op_spec(
            domain="manage",
            action="manage.shopify.connect",
            params={
                "provider": "shopify",
                "credential": token_val,
                "config": {"shop_url": "test.myshopify.com"}
            }
        )
        
        idem_key = f"idem_{token_type}"
        res = await adapter.execute(op, idem_key, session=session)
        assert res.ok is True
        
        # Verify db retrieval and mock Secret Manager values match exactly
        stmt = select(Connection).where(
            Connection.tenant_id == "test-tenant",
            Connection.brand_id == "test-brand",
            Connection.provider == "shopify"
        )
        db_res = await session.execute(stmt)
        conn = db_res.scalar_one_or_none()
        assert conn is not None
        
        assert conn.credential in mock_secrets_client.store
        secret_val = mock_secrets_client.store[conn.credential]
        assert secret_val == token_val, f"Stored token for {token_type} did not match input exactly"


# --- Idempotency Tests ---

async def test_idempotency_and_updates(session, mock_secrets_client):
    """Verify that multiple consecutive execution requests are idempotent and update state correctly."""
    adapter = ManageAdapter()
    
    op1 = make_op_spec(
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "first-token",
            "config": {"shop_url": "test.myshopify.com"}
        }
    )
    
    # 1. First execution
    res1 = await adapter.execute(op1, "idem_1", session=session)
    assert res1.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "test-tenant",
        Connection.brand_id == "test-brand",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn1 = db_res.scalar_one_or_none()
    assert conn1 is not None
    assert conn1.status == "unverified"
    
    # 2. Second execution with same parameters (simulate re-run or idempotency retry)
    res2 = await adapter.execute(op1, "idem_1_retry", session=session)
    assert res2.ok is True
    
    # Count connections in DB (should still be exactly 1)
    stmt_count = select(Connection).where(
        Connection.tenant_id == "test-tenant",
        Connection.brand_id == "test-brand",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt_count)
    conns = db_res.scalars().all()
    assert len(conns) == 1, "Expected exactly one connection row in DB, found duplicate(s)"
    
    # 3. Third execution with a different token (update intent)
    op2 = make_op_spec(
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "updated-token",
            "config": {"shop_url": "test.myshopify.com"}
        }
    )
    
    res3 = await adapter.execute(op2, "idem_2", session=session)
    assert res3.ok is True
    
    # Verify DB has exactly 1 connection and its secret resolves to the updated token
    db_res = await session.execute(stmt_count)
    conns = db_res.scalars().all()
    assert len(conns) == 1
    
    assert conns[0].credential in mock_secrets_client.store
    updated_secret_val = mock_secrets_client.store[conns[0].credential]
    assert updated_secret_val == "updated-token", "Token was not successfully updated in database/Secret Manager"
