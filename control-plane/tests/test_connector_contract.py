# Feature 1 contract, naming, and masking invariants
import pytest
from sqlalchemy import select
from app.models import Connection
from app.adapters.manage import ManageAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility

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
