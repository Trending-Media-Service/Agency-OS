import pytest
from app.kernel.tools import registry

def test_sprint2_premium_tools_registered_with_contracts():
    """Verify that all Sprint 2 premium tools are registered and conform to title/domain contracts."""
    schemas = registry.get_schemas()
    names = [s["name"] for s in schemas]
    
    # Assert presence of all 4 tools
    assert "manage_merchant_feed_shield" in names
    assert "grow_programmatic_dv360_connect" in names
    assert "grow_ai_readiness_audit" in names
    assert "grow_youtube_creator_connect" in names
    
    # Assert contracts
    for name in [
        "manage_merchant_feed_shield",
        "grow_programmatic_dv360_connect",
        "grow_ai_readiness_audit",
        "grow_youtube_creator_connect"
    ]:
        tool = registry.get_tool(name)
        assert tool is not None
        schema = tool["schema"]
        assert "title" in schema and schema["title"] != ""
        assert "domain" in schema and schema["domain"] != ""
        assert "description" in schema and schema["description"] != ""


def test_merchant_feed_shield_handler():
    """Verify that the Merchant Feed Shield tool generates correct OpSpecs."""
    tool = registry.get_tool("manage_merchant_feed_shield")
    handler = tool["handler"]
    
    specs = handler(tenant_id="t-test", brand_id="b-test", merchant_id=987654321)
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "manage.merchant_center.scan"
    assert op.domain == "manage"
    assert op.params["merchant_id"] == 987654321
    assert op.params["shield_active"] is True
    assert "policy_violations" in op.params["scan_types"]


def test_programmatic_dv360_connect_handler():
    """Verify that the DV360 programmatic media tool generates correct OpSpecs."""
    tool = registry.get_tool("grow_programmatic_dv360_connect")
    handler = tool["handler"]
    
    specs = handler(
        tenant_id="t-test",
        brand_id="b-test",
        advertiser_id="adv-112233",
        secret_ref="projects/123/secrets/dv360-token"
    )
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "grow.dv360.connect"
    assert op.domain == "grow"
    assert op.params["advertiser_id"] == "adv-112233"
    assert op.params["secret_ref"] == "projects/123/secrets/dv360-token"
    assert "high_intent_search" in op.params["sync_audiences"]


def test_ai_readiness_audit_handler():
    """Verify that the campaign AI readiness auditor generates correct OpSpecs."""
    tool = registry.get_tool("grow_ai_readiness_audit")
    handler = tool["handler"]
    
    specs = handler(tenant_id="t-test", brand_id="b-test", campaign_id="camp-pmax-99")
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "grow.ai_readiness.audit"
    assert op.domain == "grow"
    assert op.params["campaign_id"] == "camp-pmax-99"
    assert "match_type_cleanup" in op.params["checks"]
    assert op.params["target_engine"] == "broad_match_pmax"


def test_youtube_creator_connect_handler():
    """Verify that the YouTube creator connect tool generates correct OpSpecs."""
    tool = registry.get_tool("grow_youtube_creator_connect")
    handler = tool["handler"]
    
    specs = handler(tenant_id="t-test", brand_id="b-test", channel_id="UCxyz987654321")
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "grow.youtube_creator.connect"
    assert op.domain == "grow"
    assert op.params["channel_id"] == "UCxyz987654321"
    assert op.params["amplification_mode"] == "shorts_ctv_bidding"
    assert op.params["sync_creator_analytics"] is True
