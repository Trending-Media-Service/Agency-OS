# Feature 1 contract, naming, and masking invariants
import pytest
import json
import logging
from sqlalchemy import select
from app.models import Connection, AuditEvent
from app.adapters.manage import ManageAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

def test_connection_model_schema_credential():
    """Test 1: Verify database model has credential and no longer contains secret_ref."""
    attributes = dir(Connection)
    assert "credential" in attributes, "Connection model must have 'credential' attribute"
    assert "secret_ref" not in attributes, "Connection model must not have 'secret_ref' attribute"

def test_manage_adapter_plan_proposes_credential():
    """Test 2: Verify that planning translates user intent using credential param."""
    adapter = ManageAdapter()
    intent = "connect shopify secret:raw-token store.myshopify.com"
    specs = adapter.plan(intent, tenant_id="t1", brand_id="b1")
    
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "manage.shopify.connect"
    assert op.params.get("credential") == "raw-token"
    assert "secret_ref" not in op.params, "secret_ref must not be present in planned params"

def test_manage_adapter_preview_credential_masking():
    """Test 3: Verify that the preview phase masks the raw credential."""
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
    preview_artifact = adapter.preview(op)
    assert "sensitive-raw-token" not in preview_artifact.summary
    assert "Credential: ****" in preview_artifact.summary or "****" in preview_artifact.summary


def _enable_app_loggers():
    """Ensure all application loggers are enabled so we can capture their logs in tests."""
    for name in logging.root.manager.loggerDict:
        if name.startswith("app"):
            logging.getLogger(name).disabled = False


@pytest.mark.asyncio
async def test_connector_secret_hygiene(caplog, session, mock_secrets_client):
    """Test 4: Verify that no raw credentials leak into preview, logs, database config, or audit payload."""
    _enable_app_loggers()
    caplog.set_level(logging.INFO, logger="app")
    
    adapter = ManageAdapter()
    raw_token = "super-secret-token-12345"
    tenant_id = "t1"
    brand_id = "b1"
    
    # 1. Plan Phase
    intent = f"connect shopify secret:{raw_token} store.myshopify.com"
    specs = adapter.plan(intent, tenant_id=tenant_id, brand_id=brand_id)
    assert len(specs) == 1
    op = specs[0]
    
    # Assert raw token is NOT in log messages during planning
    assert raw_token not in caplog.text
    caplog.clear()
    
    # 2. Preview Phase
    preview = adapter.preview(op)
    # Assert raw token is NOT in the preview summary
    assert raw_token not in preview.summary
    assert raw_token not in caplog.text
    caplog.clear()
    
    # 3. Execute Phase
    res = await adapter.execute(op, idem_key="idem-123", session=session)
    assert res.ok
    
    # Assert raw token is NOT in the execution result detail
    res_detail_str = json.dumps(res.detail)
    assert raw_token not in res_detail_str
    
    # Assert raw token is NOT in log messages during execution
    assert raw_token not in caplog.text
    caplog.clear()
    
    # 4. Verify Database State (Connection)
    stmt = select(Connection).where(
        Connection.tenant_id == tenant_id,
        Connection.brand_id == brand_id,
        Connection.provider == "shopify"
    )
    db_res = await session.execute(stmt)
    conn_row = db_res.scalar_one()
    
    # Assert credential contains the secret reference, not the raw token!
    assert conn_row.credential != raw_token
    assert "secrets" in conn_row.credential  # Should be a secret manager ref pointer
    
    # Assert config does NOT contain the raw token!
    config_str = json.dumps(conn_row.config)
    assert raw_token not in config_str
    
    # 5. Verify Audit Log
    stmt_audit = select(AuditEvent)
    res_audit = await session.execute(stmt_audit)
    audit_rows = res_audit.scalars().all()
    for row in audit_rows:
        payload_str = json.dumps(row.payload)
        assert raw_token not in payload_str


@pytest.mark.asyncio
async def test_connector_secret_hygiene_log_leak_negative(caplog, session, mock_secrets_client):
    """Verify that test_connector_secret_hygiene would fail if a raw credential is leaked to logs."""
    _enable_app_loggers()
    caplog.set_level(logging.INFO, logger="app")
    
    adapter = ManageAdapter()
    raw_token = "leaked-token-xyz"
    tenant_id = "t1"
    brand_id = "b1"
    
    intent = f"connect shopify secret:{raw_token} store.myshopify.com"
    specs = adapter.plan(intent, tenant_id=tenant_id, brand_id=brand_id)
    op = specs[0]
    
    # Simulate a developer accidentally logging the raw token during execution
    logger = logging.getLogger("app.adapters.manage")
    logger.disabled = False  # Re-enable just in case
    
    # We patch execute to log the token and then run the original execution
    original_execute = adapter.execute
    async def mock_execute(*args, **kwargs):
        logger.info(f"DEBUG: raw token is {raw_token}")  # Accident!
        return await original_execute(*args, **kwargs)
        
    with pytest.raises(AssertionError):
        # We run the plan/preview/execute with the leak active
        preview = adapter.preview(op)
        assert raw_token not in preview.summary
        
        # Trigger the leaked execute
        res = await mock_execute(op, idem_key="idem-123", session=session)
        assert res.ok
        
        # This assertion should FAIL because the token was logged!
        assert raw_token not in caplog.text
