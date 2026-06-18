import pytest
from sqlalchemy import select
from app.adapters.manage import ManageAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money
from app.models import Connection

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
    assert op.params["secret_ref"] == "brand-name-shopify-token"
    assert op.params["config"]["shop_url"] == "brand-name.myshopify.com"

def test_manage_adapter_preview(adapter, connect_op):
    preview_art = adapter.preview(connect_op)
    assert preview_art.kind == "shopify_connect_preview"
    assert "brand-name.myshopify.com" in preview_art.summary
    assert "brand-name-shopify-token" in preview_art.summary

async def test_manage_adapter_execute_connect(adapter, connect_op, session):
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
    assert "secrets" in conn.secret_ref
    from app.services.secrets import SecretManagerClient
    secrets_client = SecretManagerClient()
    val = await secrets_client.read_secret(conn.secret_ref)
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
        secret_ref="token",
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
        secret_ref="test-secret",
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
    compensations = adapter.compensate(backup_op)
    delete_op = compensations[0]
    res = await adapter.execute(delete_op, "idem_delete_123")
    assert res.ok is True
    assert "deleted" in res.detail["message"]
