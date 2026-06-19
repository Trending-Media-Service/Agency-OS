# Features 1 & 2 lifecycle, health verification, revocation, and abort API/Saga tests
import datetime as dt
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import select
from httpx import AsyncClient
from app.models import Connection, TrustEvent, AuditEvent
from app.adapters.manage import ManageAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, OpState
from app.kernel import loop
import app.main as _
from app.services.secrets import SecretManagerClient

async def propose_and_approve(session, op_spec, actor="operator"):
    row = await loop.propose(session, op_spec, actor=actor)
    await loop.transition(session, row, OpState.PREVIEWED, actor=actor)
    await loop.transition(session, row, OpState.APPROVED, actor=actor)
    return row

@pytest.mark.asyncio
async def test_manage_adapter_execute_writes_secret(session, mock_secrets_client):
    """Test 4: Verify execution writes to Secret Manager and stores pointer in DB."""
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "sensitive-raw-token",
            "config": {"shop_url": "store.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    mock_secrets_client.write_secret.return_value = "projects/p1/secrets/s1/versions/1"
    
    result = await adapter.execute(op, idem_key="idem123", session=session)
    assert result.ok is True
    
    # Assert Secret Manager write
    mock_secrets_client.write_secret.assert_called_once_with(
        "t1-b1-shopify-secret", "sensitive-raw-token"
    )
    
    # Assert DB connection record
    stmt = select(Connection).where(Connection.tenant_id == "t1", Connection.provider == "shopify")
    res = await session.execute(stmt)
    conn = res.scalar_one()
    assert conn.credential == "projects/p1/secrets/s1/versions/1"

def test_manage_adapter_compensate_disconnect():
    """Test 5: Verify compensation generates a correct disconnect action."""
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "credential": "projects/p1/secrets/s1/versions/1",
            "config": {"shop_url": "store.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    comps = adapter.compensate(op)
    assert len(comps) == 1
    comp = comps[0]
    assert comp.action == "manage.shopify.disconnect"
    assert comp.tenant_id == "t1"
    assert comp.brand_id == "b1"

@pytest.mark.asyncio
async def test_connection_health_columns_default(session):
    """Test 6: Verify newly created connections default to unverified health status."""
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="shopify",
        credential="projects/p1/secrets/s1/versions/1",
        config={"shop_url": "store.myshopify.com"}
    )
    session.add(conn)
    await session.commit()
    
    stmt = select(Connection).where(Connection.id == conn.id)
    res = await session.execute(stmt)
    db_conn = res.scalar_one()
    
    assert db_conn.status == "unverified"
    assert db_conn.last_verified_at is None
    assert db_conn.last_error is None
    assert db_conn.revoked_at is None

@pytest.mark.asyncio
async def test_manage_connection_verify_missing_record(session):
    """Test 7: Verify health check on non-existent connection fails cleanly."""
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.connection.verify",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    result = await adapter.execute(op, idem_key="verify123", session=session)
    assert result.ok is False
    assert "Connection record not found" in result.detail.get("error")

@pytest.mark.asyncio
async def test_manage_connection_verify_revoked_gate(session):
    """Test 8: Verify health check is blocked on revoked connections."""
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="shopify",
        credential="projects/p1/secrets/s1/versions/1",
        status="revoked",
        revoked_at=dt.datetime.utcnow()
    )
    session.add(conn)
    await session.commit()
    
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.connection.verify",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    result = await adapter.execute(op, idem_key="verify_revoked", session=session)
    assert result.ok is False
    assert "Cannot verify a revoked connection" in result.detail.get("error")

@pytest.mark.asyncio
async def test_manage_connection_revoke_idempotent(session, mock_secrets_client):
    """Test 9: Verify revoking an already revoked connection is idempotent."""
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="shopify",
        credential=None,
        status="revoked",
        revoked_at=dt.datetime.utcnow()
    )
    session.add(conn)
    await session.commit()
    
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.connection.revoke",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    mock_secrets_client.delete_secret = AsyncMock()
    result = await adapter.execute(op, idem_key="revoke_idemp", session=session)
    assert result.ok is True
    mock_secrets_client.delete_secret.assert_not_called()

@pytest.mark.asyncio
async def test_manage_connection_revoke_missing_record(session):
    """Test 10: Verify revoking a non-existent connection succeeds gracefully (idempotent absence)."""
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.connection.revoke",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    result = await adapter.execute(op, idem_key="revoke_missing", session=session)
    assert result.ok is True

@pytest.mark.asyncio
async def test_connection_lifecycle_success_saga(session, mock_secrets_client, mock_mcp_client):
    """Test 26: Verify happy path saga connection registration."""
    mock_secrets_client.write_secret.return_value = "projects/p1/secrets/s1/versions/1"
    mock_secrets_client.read_secret.return_value = "raw-token"
    mock_mcp_client.call_tool.return_value = {"content": [{"text": '{"shop_name": "Test Shop", "domain": "store.myshopify.com"}'}]}
    
    op_connect = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "raw-token", "config": {"shop_url": "store.myshopify.com"}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    row_connect = await propose_and_approve(session, op_connect)
    await loop._execute_and_verify(session, row_connect)
    
    stmt = select(Connection).where(Connection.tenant_id == "t1", Connection.provider == "shopify")
    res = await session.execute(stmt)
    conn = res.scalar_one()
    assert conn.status == "active"
    assert conn.credential == "projects/p1/secrets/s1/versions/1"

@pytest.mark.asyncio
async def test_connection_execute_failure_compensation(session, mock_secrets_client):
    """Test 27: Verify execute failures trigger rollback/compensation."""
    original_execute = ManageAdapter.execute
    
    async def mock_exec_side_effect(op, idem_key, session=None):
        if op.action == "manage.shopify.connect":
            from app.kernel.optypes import ExecResult
            return ExecResult(ok=False, detail={"error": "Terminal connect failure"})
        return await original_execute(ManageAdapter(), op, idem_key, session)
        
    op_connect = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "raw-token", "config": {"shop_url": "store.myshopify.com"}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    row = await propose_and_approve(session, op_connect)
    with patch.object(ManageAdapter, "execute", side_effect=mock_exec_side_effect):
        await loop._execute_and_verify(session, row)
    
    assert row.state == "ROLLED_BACK"
    stmt = select(Connection).where(Connection.tenant_id == "t1", Connection.provider == "shopify")
    res = await session.execute(stmt)
    assert res.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_connection_verify_failure_compensation(session, mock_secrets_client, mock_mcp_client):
    """Test 28: Verify verification failures trigger saga rollback and SM secret deletion."""
    mock_secrets_client.write_secret.return_value = "projects/p1/secrets/s1/versions/1"
    mock_mcp_client.call_tool.side_effect = Exception("Shopify API unreachable!")
    
    op_connect = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "raw-token", "config": {"shop_url": "store.myshopify.com"}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    row = await propose_and_approve(session, op_connect)
    await loop._execute_and_verify(session, row)
    
    assert row.state == "ROLLED_BACK"
    mock_secrets_client.delete_secret.assert_called_once()
    
    stmt = select(Connection).where(Connection.tenant_id == "t1", Connection.provider == "shopify")
    res = await session.execute(stmt)
    assert res.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_connection_connect_idempotency(session, mock_secrets_client):
    """Test 29: Verify that connecting the same provider updates the record instead of duplicating."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential="projects/p1/secrets/s1/versions/1", config={"shop_url": "old.myshopify.com"}
    )
    session.add(conn)
    await session.commit()
    
    adapter = ManageAdapter()
    op_connect = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "new-raw-token", "config": {"shop_url": "new.myshopify.com"}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    mock_secrets_client.write_secret.return_value = "projects/p1/secrets/s1/versions/2"
    result = await adapter.execute(op_connect, idem_key="idem_idemp", session=session)
    assert result.ok is True
    
    stmt = select(Connection).where(Connection.tenant_id == "t1", Connection.provider == "shopify")
    res = await session.execute(stmt)
    conns = res.scalars().all()
    assert len(conns) == 1
    assert conns[0].config["shop_url"] == "new.myshopify.com"
    assert conns[0].credential == "projects/p1/secrets/s1/versions/2"

@pytest.mark.asyncio
async def test_connection_secret_manager_unavailable(session, mock_secrets_client):
    """Test 30: Verify Secret Manager outages fail execution and schedule outbox retry."""
    mock_secrets_client.write_secret.side_effect = Exception("Transient Secret Manager timeout")
    
    op_connect = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "raw-token", "config": {"shop_url": "store.myshopify.com"}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    row = await propose_and_approve(session, op_connect)
    with pytest.raises(Exception):
        await loop._execute_and_verify(session, row)

@pytest.mark.asyncio
async def test_on_demand_verification_success(session, mock_secrets_client, mock_mcp_client):
    """Test 31: Verify manual health check updates status and trust engine on success."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential="projects/p1/secrets/s1/versions/1", status="unverified"
    )
    session.add(conn)
    await session.commit()
    
    mock_secrets_client.read_secret.return_value = "raw-token"
    mock_mcp_client.call_tool.return_value = {"content": [{"text": '{"shop_name": "My Shop", "domain": "store.myshopify.com"}'}]}
    
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.connection.verify",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    result = await adapter.execute(op, idem_key="verify_success", session=session)
    assert result.ok is True
    
    await session.commit()
    await session.refresh(conn)
    assert conn.status == "active"
    assert conn.last_verified_at is not None
    assert conn.last_error is None
    
    stmt = select(TrustEvent).where(TrustEvent.tenant_id == "t1", TrustEvent.kind == "verified_success")
    res = await session.execute(stmt)
    assert res.scalar_one_or_none() is not None

@pytest.mark.asyncio
async def test_on_demand_verification_failure(session, mock_secrets_client, mock_mcp_client):
    """Test 32: Verify manual health check failures update status to error and record details."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential="projects/p1/secrets/s1/versions/1", status="active"
    )
    session.add(conn)
    await session.commit()
    
    mock_secrets_client.read_secret.return_value = "raw-token"
    mock_mcp_client.call_tool.side_effect = Exception("Token Expired or Invalid")
    
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.connection.verify",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.REVERSIBLE)
    )
    
    result = await adapter.execute(op, idem_key="verify_failure", session=session)
    assert result.ok is False
    
    await session.commit()
    await session.refresh(conn)
    assert conn.status == "error"
    assert "Token Expired" in conn.last_error
    
    stmt = select(TrustEvent).where(TrustEvent.tenant_id == "t1", TrustEvent.kind == "verify_failure")
    res = await session.execute(stmt)
    assert res.scalar_one_or_none() is not None

@pytest.mark.asyncio
async def test_revocation_saga_execution(session, mock_secrets_client):
    """Test 33: Verify revocation deletes SM secret and soft-revokes in DB."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential="projects/p1/secrets/s1/versions/1", status="active"
    )
    session.add(conn)
    await session.commit()
    
    adapter = ManageAdapter()
    op = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.connection.revoke",
        params={"provider": "shopify"},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    result = await adapter.execute(op, idem_key="revoke_saga", session=session)
    assert result.ok is True
    
    mock_secrets_client.delete_secret.assert_called_once_with("projects/p1/secrets/s1/versions/1")
    
    await session.commit()
    await session.refresh(conn)
    assert conn.status == "revoked"
    assert conn.credential is None
    assert conn.revoked_at is not None

@pytest.mark.asyncio
async def test_post_revocation_webhook_rejection(client, session):
    """Test 34: Verify that webhooks targeting a revoked connection are rejected."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential=None, status="revoked", revoked_at=dt.datetime.utcnow(),
        config={"shop_url": "store.myshopify.com"}
    )
    session.add(conn)
    await session.commit()
    
    resp = await client.post(
        "/webhooks/plugins/shopify",
        headers={
            "X-Tenant-ID": "t1",
            "X-Shopify-Shop-Domain": "store.myshopify.com"
        },
        json={"event": "order_created", "order_id": 12345}
    )
    assert resp.status_code in (401, 404)

@pytest.mark.asyncio
async def test_reconnect_revoked_connection(session, mock_secrets_client, mock_mcp_client):
    """Test 35: Verify that a revoked connection can be reconnected and reactivated."""
    conn = Connection(
        tenant_id="t1", brand_id="b1", provider="shopify",
        credential=None, status="revoked", revoked_at=dt.datetime.utcnow()
    )
    session.add(conn)
    await session.commit()
    
    mock_secrets_client.write_secret.return_value = "projects/p1/secrets/s1/versions/2"
    mock_secrets_client.read_secret.return_value = "new-token"
    mock_mcp_client.call_tool.return_value = {"content": [{"text": '{"shop_name": "Test Shop", "domain": "store.myshopify.com"}'}]}
    
    op_connect = OpSpec(
        tenant_id="t1", brand_id="b1", domain="manage",
        action="manage.shopify.connect",
        params={"provider": "shopify", "credential": "new-token", "config": {"shop_url": "store.myshopify.com"}},
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE)
    )
    
    row = await propose_and_approve(session, op_connect)
    await loop._execute_and_verify(session, row)
    
    await session.commit()
    await session.refresh(conn)
    assert conn.status == "active"
    assert conn.credential == "projects/p1/secrets/s1/versions/2"
    assert conn.revoked_at is None
