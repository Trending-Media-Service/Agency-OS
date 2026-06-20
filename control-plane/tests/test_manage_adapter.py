import pytest
from sqlalchemy import select
from app.adapters.manage import ManageAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Connection

@pytest.fixture(autouse=True)
def mock_datetime_now(monkeypatch):
    import datetime
    
    class MockDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2026, 6, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)
            
    class MockDatetimeModule:
        def __getattr__(self, name):
            if name == "datetime":
                return MockDatetime
            return getattr(datetime, name)
            
    monkeypatch.setattr("app.adapters.manage.datetime", MockDatetimeModule())

@pytest.fixture
def adapter():
    return ManageAdapter()

@pytest.fixture
def connect_intent():
    return "connect shopify store brand-name.myshopify.com with secret:brand-name-shopify-token"

@pytest.fixture
def connect_op(adapter, connect_intent):
    ops = adapter.plan(connect_intent, "t1", "b1")
    assert len(ops) == 1
    return ops[0]

def test_manage_adapter_plan(adapter, connect_intent):
    ops = adapter.plan(connect_intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "manage.shopify.connect"
    assert op.params["provider"] == "shopify"
    assert op.params["credential"] == "brand-name-shopify-token"
    assert op.params["config"]["shop_url"] == "brand-name.myshopify.com"

def test_manage_adapter_preview(adapter, connect_op):
    preview_art = adapter.preview(connect_op)
    assert preview_art.kind == "shopify_connect_preview"
    assert "brand-name.myshopify.com" in preview_art.summary
    assert "****" in preview_art.summary

async def test_manage_adapter_execute_connect(adapter, connect_op, session, mock_secrets_client):
    # Execute connect
    res = await adapter.execute(connect_op, "idem_connect_123", session=session)
    assert res.ok is True
    
    # Verify DB entry
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    assert "secrets" in conn.credential
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "brand-name-shopify-token"
    assert conn.config["shop_url"] == "brand-name.myshopify.com"

@pytest.mark.asyncio
async def test_manage_adapter_verify(adapter, connect_op, session):
    await adapter.execute(connect_op, "idem_shopify_verify_setup_123", session=session)
    verdict = await adapter.verify(connect_op, session=session)
    assert verdict.ok is True
    assert verdict.checks["credentials_valid"] is True

def test_manage_adapter_compensate(adapter, connect_op):
    compensations = adapter.compensate(connect_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "manage.shopify.disconnect"
    assert comp.params["provider"] == "shopify"

async def test_manage_adapter_execute_disconnect(adapter, connect_op, session):
    # 1. Insert connection first
    conn = Connection(
        tenant_id="t1",
        brand_id="b1",
        provider="shopify",
        credential="token",
        config={"shop_url": "url"}
    )
    session.add(conn)
    await session.commit()
    
    # 2. Get compensation Op (disconnect)
    compensations = adapter.compensate(connect_op)
    disconnect_op = compensations[0]
    
    # 3. Execute disconnect
    res = await adapter.execute(disconnect_op, "idem_disconnect_123", session=session)
    assert res.ok is True
    
    # 4. Verify DB entry is gone
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn_after = db_res.scalar_one_or_none()
    assert conn_after is None


async def test_get_brand_status_not_connected(client):
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert resp.status_code == 200
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]
    
    H = {"X-Tenant-Id": tid}
    resp_status = await client.get(f"/brands/{bid}/status", headers=H)
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert status_data["shopify_connected"] is False
    assert status_data["metrics"] == {}


async def test_get_brand_status_connected(client, session):
    resp = await client.post("/tenants", json={"name": "Test Tenant", "brand_name": "Test Brand"})
    assert resp.status_code == 200
    data = resp.json()
    tid = data["tenant_id"]
    bid = data["brand_id"]
    
    conn = Connection(
        tenant_id=tid,
        brand_id=bid,
        provider="shopify",
        credential="test-secret",
        config={"shop_url": "test-brand.myshopify.com"}
    )
    session.add(conn)
    await session.commit()
    
    H = {"X-Tenant-Id": tid}
    resp_status = await client.get(f"/brands/{bid}/status", headers=H)
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert status_data["shopify_connected"] is True
    assert status_data["metrics"]["shop_name"] == "Test-brand"
    assert status_data["metrics"]["product_count"] == 42


@pytest.fixture
def backup_op(adapter):
    ops = adapter.plan("create backup", "t1", "b1")
    assert len(ops) == 1
    return ops[0]


def test_manage_adapter_backup_plan(adapter):
    ops = adapter.plan("take snapshot", "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.action == "manage.backup.create"
    assert op.params["db_name"] == "db-b1"
    assert "gs://aos-backups-t1/b1" in op.params["target_bucket"]
    assert op.params["backup_file"].endswith(".sql")


def test_manage_adapter_backup_preview(adapter, backup_op):
    preview_art = adapter.preview(backup_op)
    assert preview_art.kind == "db_backup_preview"
    assert "db-b1" in preview_art.summary
    assert backup_op.params["backup_file"] in preview_art.summary


async def test_manage_adapter_backup_execute(adapter, backup_op):
    res = await adapter.execute(backup_op, "idem_backup_123")
    assert res.ok is True
    assert "backup_file" in res.detail
    assert res.detail["backup_file"] == backup_op.params["backup_file"]


@pytest.mark.asyncio
async def test_manage_adapter_backup_verify(adapter, backup_op):
    # Execute backup first in this test's isolated GCS mock environment
    await adapter.execute(backup_op, "idem_backup_verify_prep")
    verdict = await adapter.verify(backup_op)
    assert verdict.ok is True
    assert verdict.checks["file_exists"] is True


def test_manage_adapter_backup_compensate(adapter, backup_op):
    compensations = adapter.compensate(backup_op)
    assert len(compensations) == 1
    comp = compensations[0]
    assert comp.action == "manage.backup.delete"
    assert comp.params["backup_file"] == backup_op.params["backup_file"]


async def test_manage_adapter_backup_execute_delete(adapter, backup_op):
    # Execute backup first in this test's isolated GCS mock environment
    await adapter.execute(backup_op, "idem_backup_delete_prep")
    compensations = adapter.compensate(backup_op)
    delete_op = compensations[0]
    res = await adapter.execute(delete_op, "idem_delete_123")
    assert res.ok is True
    assert "deleted" in res.detail["message"]


async def test_manage_adapter_backup_degraded_flow(adapter, backup_op, monkeypatch):
    from app.services.storage import GcsClient
    import os
    import shutil
    
    # Simulate production mode with GCS outage
    gcs_instance = GcsClient()
    gcs_instance._client = object() # Mock active GCP client
    
    async def mock_upload(*args, **kwargs):
        raise Exception("GCS Outage Sim")
        
    async def mock_exists(*args, **kwargs):
        raise Exception("GCS Outage Sim")
        
    monkeypatch.setattr(gcs_instance, "upload_from_string", mock_upload)
    monkeypatch.setattr(gcs_instance, "blob_exists", mock_exists)
    monkeypatch.setattr("app.adapters.manage.GcsClient", lambda *a, **kw: gcs_instance)
    
    # Clear fallback directory
    fallback_dir = os.path.join(os.path.dirname(__file__), "../scratch/fallback_backups")
    if os.path.exists(fallback_dir):
        shutil.rmtree(fallback_dir)
        
    # 1. Execute backup (should fallback to local disk and return degraded success)
    res = await adapter.execute(backup_op, "idem_backup_degraded_123")
    assert res.ok is True
    assert res.detail["storage_status"] == "degraded"
    assert "fallback_file" in res.detail
    fallback_file = res.detail["fallback_file"]
    assert os.path.exists(fallback_file)
    
    # 2. Verify backup (should check fallback storage and return degraded success)
    verdict = await adapter.verify(backup_op)
    assert verdict.ok is True
    assert verdict.checks["file_exists_in_fallback"] is True
    assert verdict.checks["storage_status"] == "degraded"
    
    # 3. Compensate (delete)
    compensations = adapter.compensate(backup_op)
    delete_op = compensations[0]
    
    async def mock_delete(*args, **kwargs):
        raise Exception("GCS Outage Sim")
    monkeypatch.setattr(gcs_instance, "delete_blob", mock_delete)
    
    # Delete should clean up fallback file and return degraded success
    res_del = await adapter.execute(delete_op, "idem_delete_degraded_123")
    assert res_del.ok is True
    assert res_del.detail["storage_status"] == "degraded"
    assert not os.path.exists(fallback_file)


@pytest.mark.asyncio
async def test_manage_adapter_real_shopify_mcp_verification(adapter, session, mock_secrets_client):
    # 1. Plan with custom mcp_url
    intent = "connect shopify store luxury-tea.myshopify.com with secret:luxury-secret-token mcp_url:https://mcp-shopify.tms.internal/rpc"
    ops = adapter.plan(intent, "t1", "b1")
    assert len(ops) == 1
    op = ops[0]
    assert op.params["config"]["mcp_server_url"] == "https://mcp-shopify.tms.internal/rpc"
    assert op.params["config"]["shop_url"] == "luxury-tea.myshopify.com"

    # 2. Execute connection (registers in DB)
    res = await adapter.execute(op, "idem_luxury_conn", session=session)
    assert res.ok is True

    # 3. Verify (should make a real HTTP call to the custom MCP server URL)
    from unittest.mock import patch, MagicMock
    with patch("httpx.AsyncClient.post") as mock_post:
        # Mock successful JSON-RPC tool call response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"shop_name": "Luxury Tea Boutique", "domain": "luxury-tea.myshopify.com", "currency": "USD", "status": "active"}'
                    }
                ]
            }
        }
        mock_post.return_value = mock_resp

        verdict = await adapter.verify(op, session=session)
        assert verdict.ok is True
        assert verdict.checks["mcp_tool_call_ok"] is True
        assert verdict.detail["shop_name"] == "Luxury Tea Boutique"
        assert verdict.detail["domain"] == "luxury-tea.myshopify.com"

        # Assert correct HTTP post details
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        url = args[0]
        payload = kwargs["json"]

        assert url == "https://mcp-shopify.tms.internal/rpc"
        assert payload["method"] == "tools/call"
        assert payload["params"]["name"] == "shopify_get_shop_info"

# Backward Compatibility Tests
@pytest.mark.asyncio
async def test_manage_adapter_execute_connect_backward_compatibility(adapter, session, mock_secrets_client):
    op = OpSpec(
        tenant_id="t1",
        brand_id="b1",
        domain="manage",
        action="manage.shopify.connect",
        params={
            "provider": "shopify",
            "secret_ref": "legacy-shopify-token",
            "config": {"shop_url": "brand-name.myshopify.com"}
        },
        severity=Severity(impact=1, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=0, currency="INR"),
    )
    res = await adapter.execute(op, "idem_shopify_legacy_123", session=session)
    assert res.ok is True
    
    stmt = select(Connection).where(
        Connection.tenant_id == "t1",
        Connection.brand_id == "b1",
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn = db_res.scalar_one_or_none()
    assert conn is not None
    
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.credential)
    assert val == "legacy-shopify-token"
