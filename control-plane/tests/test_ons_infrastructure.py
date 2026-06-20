import pytest
from app.adapters.provision import ProvisionAdapter
from app.kernel.optypes import OpSpec, Severity, Reversibility, Money

@pytest.fixture
def adapter():
    return ProvisionAdapter()

@pytest.fixture
def custom_domain_op():
    return OpSpec(
        id="op_ons_111",
        tenant_id="t-ons-tenant",
        brand_id="b-ons-brand",
        domain="provision",
        action="provision.web_host.create",
        params={"domain": "ableys.in", "recipe": "web-host", "version": "0.1.0"},
        severity=Severity(impact=2, reversibility=Reversibility.COMPENSATABLE),
        cost_estimate=Money(amount_minor=250_000, currency="INR"),
    )

@pytest.mark.asyncio
async def test_ons_provision_workflow(adapter, custom_domain_op):
    """Verify the full ONS provisioning lifecycle for a custom-domain web host."""
    # 1. Preview (Simulate planning/validation)
    preview_art = adapter.preview(custom_domain_op)
    assert preview_art.kind == "terraform_plan"
    assert "Plan: 5 to add" in preview_art.summary
    
    # 2. Execute (Verify ONS outputs: Load Balancer IP, SSL DNS Zone Name Servers, Service URL)
    res = await adapter.execute(custom_domain_op, "idem_ons_111")
    assert res.ok is True
    assert "outputs" in res.detail
    
    outputs = res.detail["outputs"]
    assert outputs["service_url"] == "https://web-ableys.in"
    assert outputs["lb_ip"] == "34.120.15.22"
    
    # Assert that the new ONS output 'dns_zone_name_servers' is populated
    assert "dns_zone_name_servers" in outputs
    ns_list = outputs["dns_zone_name_servers"]
    assert len(ns_list) == 2
    assert ns_list[0] == "ns-cloud-a1.googledomains.com."
    
    # Assert that the correct simulation costs (GCP resources) were ingested
    assert len(res.costs) > 0
    gcp_resource_cost = next((c for c in res.costs if c.kind == "gcp_resource"), None)
    assert gcp_resource_cost is not None
    assert gcp_resource_cost.meta["recipe"] == "web-host"

    # 3. Verify (Confirm post-provision checks pass successfully)
    res_v = await adapter.verify(custom_domain_op)
    assert res_v.ok is True
    assert res_v.checks["http_200"] is True
