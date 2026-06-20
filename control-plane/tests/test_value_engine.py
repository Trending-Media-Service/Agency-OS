import pytest
from app.kernel.tools import registry

def test_premium_tools_registered_with_contracts():
    """Verify that all Sprint 1 premium tools are registered and conform to title/domain contracts."""
    schemas = registry.get_schemas()
    names = [s["name"] for s in schemas]
    
    # Assert presence
    assert "grow_value_engine_optimize" in names
    assert "presence_consent_mode_audit" in names
    assert "grow_meridian_mmm_audit" in names
    
    # Assert contracts (F-6 titles and domains)
    for name in ["grow_value_engine_optimize", "presence_consent_mode_audit", "grow_meridian_mmm_audit"]:
        tool = registry.get_tool(name)
        assert tool is not None
        schema = tool["schema"]
        assert "title" in schema and schema["title"] != ""
        assert "domain" in schema and schema["domain"] != ""
        assert "description" in schema and schema["description"] != ""


def test_value_engine_math_conservative():
    """Verify the V_opt formula and ROAS multiplier under a Conservative posture."""
    tool = registry.get_tool("grow_value_engine_optimize")
    handler = tool["handler"]
    
    # Micro-conversions:
    # 1. add_to_cart: val=2000, dropoff=0.20 => net = 2000 * 0.80 = 1600
    # 2. newsletter: val=5000, dropoff=0.50 => net = 5000 * 0.50 = 2500
    # Expected V_opt = V_macro (10000) + 1600 + 2500 = 14100
    micro_conversions = [
        {"name": "add_to_cart", "value_minor": 2000, "dropoff_rate": 0.20},
        {"name": "newsletter", "value_minor": 5000, "dropoff_rate": 0.50}
    ]
    
    specs = handler(
        tenant_id="t-test",
        brand_id="b-test",
        campaign_id="camp-123",
        posture="conservative",
        macro_value_minor=10000,
        micro_conversions=micro_conversions
    )
    
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "grow.value_bidding.optimize"
    assert op.domain == "grow"
    assert op.params["v_opt_minor"] == 14100
    assert op.params["roas_multiplier"] == 1.10
    assert op.params["macro_value_minor"] == 10000
    assert op.params["posture"] == "conservative"
    assert op.params["micro_conversions_audited"] == 2


def test_value_engine_math_aggressive():
    """Verify the V_opt formula and ROAS multiplier under an Aggressive posture."""
    tool = registry.get_tool("grow_value_engine_optimize")
    handler = tool["handler"]
    
    # Micro-conversions:
    # 1. add_to_cart: val=1000, dropoff=0.10 => net = 1000 * 0.90 = 900
    # Expected V_opt = V_macro (5000) + 900 = 5900
    # Expected ROAS multiplier = 0.85
    micro_conversions = [
        {"name": "add_to_cart", "value_minor": 1000, "dropoff_rate": 0.10}
    ]
    
    specs = handler(
        tenant_id="t-test",
        brand_id="b-test",
        campaign_id="camp-123",
        posture="aggressive",
        macro_value_minor=5000,
        micro_conversions=micro_conversions
    )
    
    assert len(specs) == 1
    op = specs[0]
    assert op.params["v_opt_minor"] == 5900
    assert op.params["roas_multiplier"] == 0.85
    assert op.params["posture"] == "aggressive"


def test_consent_mode_audit_handler():
    """Verify that the Consent Mode auditor tool generates valid OpSpecs."""
    tool = registry.get_tool("presence_consent_mode_audit")
    handler = tool["handler"]
    
    specs = handler(tenant_id="t-test", brand_id="b-test", url="https://brand.in")
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "presence.consent_mode.audit"
    assert op.domain == "presence"
    assert op.params["url"] == "https://brand.in"
    assert op.params["audit_mode"] == "consent-v2-verification"


def test_meridian_mmm_audit_handler():
    """Verify that the Meridian MMM auditor tool generates valid OpSpecs."""
    tool = registry.get_tool("grow_meridian_mmm_audit")
    handler = tool["handler"]
    
    specs = handler(tenant_id="t-test", brand_id="b-test", lookback_days=120)
    assert len(specs) == 1
    op = specs[0]
    assert op.action == "grow.meridian_mmm.audit"
    assert op.domain == "grow"
    assert op.params["lookback_days"] == 120
    assert "search" in op.params["channels"]
    assert op.params["report_format"] == "cfo-ready-pdf"
